"""
External G1 benchmark runner.

Runs HumanEval and MBPP coding tasks against the existing HarmoNet and
LangGraph adapters, then validates generated code by executing the benchmark
tests in a short-lived Python subprocess.

This is intentionally self-contained and dependency-light. It downloads the
public benchmark files from the official GitHub repositories into
`benchmark_data/` and writes JSON/CSV/report artifacts next to the chosen
output path.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import gzip
import io
import json
import logging
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.request import urlopen

from benchmark.agents_harmonet import HarmoNetAdapter
from benchmark.tasks import BenchmarkTask


HUMANEVAL_URL = (
    "https://raw.githubusercontent.com/openai/human-eval/master/"
    "data/HumanEval.jsonl.gz"
)
MBPP_URL = (
    "https://raw.githubusercontent.com/google-research/google-research/master/"
    "mbpp/sanitized-mbpp.json"
)

DATA_DIR = Path("benchmark_data")

COMMON_PREAMBLE = """
from typing import *
import collections
import functools
import itertools
import math
import operator
import re
import string
import heapq
import bisect
import statistics
""".strip()

BLOCKED_IMPORTS = {
    "ctypes",
    "http",
    "httpx",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}
BLOCKED_CALLS = {"compile", "eval", "exec", "input", "open", "__import__"}


def _quiet_framework_logs() -> None:
    for name in [
        "httpx",
        "openai",
        "autogen_core",
        "autogen_core.events",
        "autogen_core.trace",
        "autogen_agentchat",
        "autogen_ext",
        "crewai",
        "litellm",
    ]:
        logging.getLogger(name).setLevel(logging.WARNING)


@dataclass
class ExternalTask:
    benchmark: str
    task_id: str
    prompt: str
    entry_point: str
    tests: str
    test_setup: str = ""
    humaneval_prefix: str = ""


@dataclass
class ExternalMeasurement:
    system: str
    benchmark: str
    task_id: str
    repeat: int
    passed: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    eval_error: str
    output_chars: int
    extracted_chars: int
    metadata: Dict[str, Any]
    token_source: str = "unknown"


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    with urlopen(url, timeout=60) as resp:
        path.write_bytes(resp.read())


def _jsonl_gz(path: Path) -> Iterable[Dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _infer_entry_point_from_tests(tests: Iterable[str]) -> str:
    for test in tests:
        match = re.search(r"assert\s+([A-Za-z_]\w*)\s*\(", test)
        if match:
            return match.group(1)
    return "candidate"


def load_humaneval(limit: Optional[int]) -> List[ExternalTask]:
    path = DATA_DIR / "HumanEval.jsonl.gz"
    _download(HUMANEVAL_URL, path)
    tasks = []
    for item in _jsonl_gz(path):
        entry = item["entry_point"]
        prompt = (
            "Complete this HumanEval Python function. Return only Python code. "
            "Include the full function definition if possible.\n\n"
            f"{item['prompt']}"
        )
        tasks.append(
            ExternalTask(
                benchmark="humaneval",
                task_id=item["task_id"],
                prompt=prompt,
                entry_point=entry,
                tests=item["test"],
                humaneval_prefix=item["prompt"],
            )
        )
        if limit and len(tasks) >= limit:
            break
    return tasks


def load_mbpp(limit: Optional[int]) -> List[ExternalTask]:
    path = DATA_DIR / "sanitized-mbpp.json"
    _download(MBPP_URL, path)
    items = json.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for item in items:
        tests = item.get("test_list") or []
        entry = _infer_entry_point_from_tests(tests)
        prompt_text = item.get("prompt") or item.get("text") or ""
        prompt = (
            "Solve this MBPP Python programming task. Return only Python code. "
            f"The solution must define function `{entry}`.\n\n"
            f"Task: {prompt_text}\n\n"
            "Public tests:\n"
            + "\n".join(tests[:3])
        )
        test_setup = "\n".join(item.get("test_imports") or [])
        tasks.append(
            ExternalTask(
                benchmark="mbpp",
                task_id=f"mbpp_{item.get('task_id', len(tasks))}",
                prompt=prompt,
                entry_point=entry,
                tests="\n".join(tests),
                test_setup=test_setup,
            )
        )
        if limit and len(tasks) >= limit:
            break
    return tasks


def load_tasks(benchmarks: List[str], limit_per_benchmark: Optional[int]) -> List[ExternalTask]:
    tasks: List[ExternalTask] = []
    if "humaneval" in benchmarks:
        tasks.extend(load_humaneval(limit_per_benchmark))
    if "mbpp" in benchmarks:
        tasks.extend(load_mbpp(limit_per_benchmark))
    return tasks


def _extract_code(output: str, task: ExternalTask) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*(.*?)```", output, flags=re.I | re.S)
    if blocks:
        preferred = [b for b in blocks if f"def {task.entry_point}" in b]
        code = max(preferred or blocks, key=len).strip()
    else:
        marker = f"def {task.entry_point}"
        if marker in output:
            code = output[output.index(marker) :].strip()
        else:
            match = re.search(r"(^|\n)(from\s+\S+\s+import\s+|import\s+|def\s+)", output)
            code = output[match.start() :].strip() if match else output.strip()

    code = code.replace("\r\n", "\n")
    if f"def {task.entry_point}" not in code and task.humaneval_prefix:
        code = f"{task.humaneval_prefix.rstrip()}\n{code}"
    return f"{COMMON_PREAMBLE}\n\n{code}\n"


def _safety_error(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"syntax error before execution: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BLOCKED_IMPORTS:
                    return f"blocked import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in BLOCKED_IMPORTS:
                return f"blocked import: {node.module}"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_CALLS:
                return f"blocked call: {func.id}"
            if isinstance(func, ast.Attribute) and func.attr in BLOCKED_CALLS:
                return f"blocked call: {func.attr}"
    return ""


def evaluate_code(code: str, task: ExternalTask, timeout_s: float) -> tuple[bool, str]:
    safety = _safety_error(code)
    if safety:
        return False, safety

    if task.benchmark == "humaneval":
        test_code = (
            f"{code}\n\n{task.test_setup}\n\n{task.tests}\n\n"
            f"check({task.entry_point})\n"
        )
    else:
        test_code = f"{code}\n\n{task.test_setup}\n\n{task.tests}\n"

    with tempfile.TemporaryDirectory(prefix="harmonet_ext_g1_") as tmp:
        path = Path(tmp) / "candidate_test.py"
        path.write_text(test_code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(path)],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return False, f"timeout > {timeout_s}s"

    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, "\n".join(err[-6:])[:1000]


def _to_benchmark_task(task: ExternalTask) -> BenchmarkTask:
    return BenchmarkTask(
        id=task.task_id,
        category=task.benchmark,
        prompt=task.prompt,
        expected_keywords=[task.entry_point],
        complexity=2,
    )


def _run_one(adapter: Any, task: ExternalTask, repeat: int, timeout_s: float) -> ExternalMeasurement:
    t0 = time.perf_counter()
    prompt_tokens = completion_tokens = total_tokens = 0
    output = ""
    metadata: Dict[str, Any] = {}
    eval_error = ""
    passed = False

    try:
        if os.getenv("BENCHMARK_VERBOSE_FRAMEWORK_LOGS", "0") == "1":
            result = adapter.run(_to_benchmark_task(task))
        else:
            _quiet_framework_logs()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = adapter.run(_to_benchmark_task(task))
        output = str(result.get("output", ""))
        token_source = str(result.get("token_source", "unknown"))
        prompt_tokens = int(result.get("prompt_tokens", 0))
        completion_tokens = int(result.get("completion_tokens", 0))
        total_tokens = prompt_tokens + completion_tokens
        metadata = dict(result.get("metadata", {}))
        code = _extract_code(output, task)
        passed, eval_error = evaluate_code(code, task, timeout_s)
        if (
            not passed
            and os.getenv("HARMONET_V2_EVAL_REPAIR", "1") == "1"
            and hasattr(adapter, "repair_after_eval")
            and os.getenv("G1_DISABLE_EVAL_REPAIR", "").lower() not in ("1", "true", "yes")
        ):
            repair_started = time.perf_counter()
            repair = adapter.repair_after_eval(_to_benchmark_task(task), output, eval_error)
            repaired_output = str(repair.get("output", ""))
            repaired_code = _extract_code(repaired_output, task)
            repaired_passed, repaired_error = evaluate_code(repaired_code, task, timeout_s)
            prompt_tokens += int(repair.get("prompt_tokens", 0) or 0)
            completion_tokens += int(repair.get("completion_tokens", 0) or 0)
            total_tokens = prompt_tokens + completion_tokens
            metadata["eval_repair"] = dict(repair.get("metadata", {}))
            metadata["eval_repair"]["latency_s"] = round(time.perf_counter() - repair_started, 4)
            if repaired_passed:
                output = repaired_output
                passed = True
                eval_error = ""
            else:
                eval_error = repaired_error or eval_error
    except Exception as exc:
        eval_error = f"runner error: {exc}"

    latency = time.perf_counter() - t0
    return ExternalMeasurement(
        system=adapter.name,
        benchmark=task.benchmark,
        task_id=task.task_id,
        repeat=repeat,
        passed=passed,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        token_source=locals().get("token_source", "unknown"),
        total_tokens=total_tokens,
        latency_seconds=round(latency, 4),
        eval_error=eval_error,
        output_chars=len(output),
        extracted_chars=len(_extract_code(output, task)) if output else 0,
        metadata=metadata,
    )


def _mean(values: List[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _ci95(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    return 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _p99(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.99) - 1)]


def summarize(system: str, measurements: List[ExternalMeasurement]) -> Dict[str, Any]:
    passed = [1.0 if m.passed else 0.0 for m in measurements]
    tokens = [float(m.total_tokens) for m in measurements]
    latencies = [float(m.latency_seconds) for m in measurements]
    return {
        "system": system,
        "runs": len(measurements),
        "pass_rate": round(_mean(passed), 4),
        "pass_rate_ci95": round(_ci95(passed), 4),
        "avg_total_tokens": round(_mean(tokens), 1),
        "avg_total_tokens_ci95": round(_ci95(tokens), 1),
        "avg_latency_s": round(_mean(latencies), 3),
        "avg_latency_ci95_s": round(_ci95(latencies), 3),
        "p99_latency_s": round(_p99(latencies), 3),
    }


def print_report(results: Dict[str, List[ExternalMeasurement]]) -> str:
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("External Standard G1: HumanEval / MBPP")
    lines.append("=" * 80)
    lines.append(
        f"{'system':<58} {'pass':>8} {'tokens':>10} {'lat(s)':>9} {'p99':>8}"
    )
    lines.append("-" * 80)

    summaries = {name: summarize(name, ms) for name, ms in results.items()}
    for name, s in summaries.items():
        lines.append(
            f"{name:<58} "
            f"{s['pass_rate']*100:>6.1f}%+/-{s['pass_rate_ci95']*100:<4.1f} "
            f"{s['avg_total_tokens']:>10.0f} "
            f"{s['avg_latency_s']:>9.2f} "
            f"{s['p99_latency_s']:>8.2f}"
        )

    harmonet = next((s for n, s in summaries.items() if n == "harmonet"), None)
    langraph = next((s for n, s in summaries.items() if "langraph" in n), None)
    if harmonet and langraph:
        tok_ratio = harmonet["avg_total_tokens"] / max(1, langraph["avg_total_tokens"])
        success_gap = harmonet["pass_rate"] - langraph["pass_rate"]
        g1_1 = tok_ratio <= 0.70
        g1_2 = success_gap >= -0.05
        g1_3 = harmonet["p99_latency_s"] <= 30.0
        lines.append("\nG1 gate")
        lines.append(f"G1-1 token ratio: {tok_ratio:.2%} {'PASS' if g1_1 else 'FAIL'}")
        lines.append(f"G1-2 pass gap: {success_gap*100:+.1f}pp {'PASS' if g1_2 else 'FAIL'}")
        lines.append(f"G1-3 HarmoNet p99: {harmonet['p99_latency_s']:.2f}s {'PASS' if g1_3 else 'FAIL'}")
        lines.append(f"G1: {sum([g1_1, g1_2, g1_3])}/3 {'GO' if sum([g1_1, g1_2, g1_3]) >= 2 else 'NO-GO'}")

    lines.append("\nBy benchmark")
    for bench in sorted({m.benchmark for ms in results.values() for m in ms}):
        lines.append(f"  {bench}:")
        for name, ms in results.items():
            subset = [m for m in ms if m.benchmark == bench]
            if subset:
                s = summarize(name, subset)
                lines.append(
                    f"    {name:<54} pass={s['pass_rate']*100:5.1f}% "
                    f"tokens={s['avg_total_tokens']:7.0f} lat={s['avg_latency_s']:6.2f}s"
                )

    report = "\n".join(lines)
    print(report)
    return report


def save_artifacts(
    output_path: Path,
    results: Dict[str, List[ExternalMeasurement]],
    tasks: List[ExternalTask],
    report: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "benchmarks": sorted({t.benchmark for t in tasks}),
            "task_count": len(tasks),
            "sources": {
                "humaneval": HUMANEVAL_URL,
                "mbpp": MBPP_URL,
            },
            "backend": os.getenv("HARMONET_LLM_BACKEND", ""),
            "runyourai_model": os.getenv("RUNYOURAI_MODEL", ""),
        },
        "systems": [
            {
                "summary": summarize(name, ms),
                "measurements": [asdict(m) for m in ms],
            }
            for name, ms in results.items()
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = output_path.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "system",
            "benchmark",
            "task_id",
            "repeat",
            "passed",
            "prompt_tokens",
            "completion_tokens",
            "token_source",
            "total_tokens",
            "latency_seconds",
            "eval_error",
        ])
        for ms in results.values():
            for m in ms:
                writer.writerow([
                    m.system,
                    m.benchmark,
                    m.task_id,
                    m.repeat,
                    m.passed,
                    m.prompt_tokens,
                    m.completion_tokens,
                    m.token_source,
                    m.total_tokens,
                    m.latency_seconds,
                    m.eval_error,
                ])

    report_path = output_path.with_name(output_path.stem + "_report.txt")
    report_path.write_text(report, encoding="utf-8")
    print(f"\nSaved: {output_path}")
    print(f"Saved: {csv_path}")
    print(f"Saved: {report_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run external standard G1 benchmarks.")
    parser.add_argument("--benchmarks", default="humaneval,mbpp")
    parser.add_argument("--limit-per-benchmark", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--harmonet-ticks", type=int, default=2)
    parser.add_argument("--eval-timeout", type=float, default=5.0)
    parser.add_argument("--output", default="g1_external_results.json")
    parser.add_argument(
        "--adapters",
        default="harmonet,langraph",
        help="Comma-separated adapters: single, harmonet, harmonet_v2, langraph, autogen, crewai",
    )
    parser.add_argument("--skip-harmonet", action="store_true")
    parser.add_argument("--skip-langraph", action="store_true")
    args = parser.parse_args()

    benchmarks = [b.strip().lower() for b in args.benchmarks.split(",") if b.strip()]
    tasks = load_tasks(benchmarks, args.limit_per_benchmark)
    if not tasks:
        raise SystemExit("No external tasks loaded.")

    adapter_names = [a.strip().lower() for a in args.adapters.split(",") if a.strip()]
    adapters = []
    if "harmonet" in adapter_names and not args.skip_harmonet:
        adapters.append(HarmoNetAdapter(ticks=args.harmonet_ticks))
    if "single" in adapter_names:
        from benchmark.agents_single import SingleCallAdapter

        adapters.append(SingleCallAdapter())

    if "harmonet_v2" in adapter_names and not args.skip_harmonet:
        from benchmark.agents_harmonet_v2 import HarmoNetV2Adapter

        adapters.append(HarmoNetV2Adapter(ticks=args.harmonet_ticks))
    if "langraph" in adapter_names and not args.skip_langraph:
        from benchmark.agents_langraph import LangGraphAdapter

        adapters.append(LangGraphAdapter())
    if "autogen" in adapter_names:
        from benchmark.agents_autogen import AutoGenAdapter

        adapters.append(AutoGenAdapter())
    if "crewai" in adapter_names:
        from benchmark.agents_crewai import CrewAIAdapter

        adapters.append(CrewAIAdapter())

    print(
        f"External G1 tasks={len(tasks)} benchmarks={benchmarks} "
        f"repeats={args.repeats} adapters={[a.name for a in adapters]}"
    )

    results: Dict[str, List[ExternalMeasurement]] = {}
    for adapter in adapters:
        system_results: List[ExternalMeasurement] = []
        print(f"\n--- {adapter.name} ---")
        for idx, task in enumerate(tasks, 1):
            for repeat in range(1, args.repeats + 1):
                label = f"[{adapter.name}] {idx}/{len(tasks)} {task.task_id} r{repeat}"
                print(label, "...", end=" ", flush=True)
                measurement = _run_one(adapter, task, repeat, args.eval_timeout)
                system_results.append(measurement)
                status = "PASS" if measurement.passed else "FAIL"
                print(
                    f"{status} {measurement.total_tokens}tok "
                    f"{measurement.latency_seconds:.1f}s"
                )
        results[adapter.name] = system_results

    report = print_report(results)
    save_artifacts(Path(args.output), results, tasks, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
