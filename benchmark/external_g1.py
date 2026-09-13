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
import builtins
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
# 진입점 추론 폴백에서 제외할 이름 (set, sum, len, sorted …)
# import된 모듈 안에서 __builtins__는 dict라 dir()이 builtin 이름을 안 줌 → builtins 모듈 사용
BUILTIN_NAMES = frozenset(dir(builtins)) | {"math", "re", "collections", "itertools"}

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
    candidate_code: str = ""        # 채점된 산출물 전문 (A7c: 저장하지 않으면 증거가 아니다)
    extraction: str = ""            # fenced | heuristic | raw | prefix — 산출물을 어떻게 뽑았는지
    outcome: str = ""               # verify.score_hidden outcome
    hidden_exposed: bool = False    # 채점 테스트가 프롬프트에 노출된 벤치마크(MBPP) 면 True


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


def _infer_entry_point_from_tests(tests: Iterable[str], code: str = "") -> str:
    """
    MBPP 진입점 추론. 참조 코드의 마지막 최상위 def를 우선 사용.
    (구 정규식은 `assert set(f(...)) == ...`에서 `set`을 잡아 mbpp_2/7의 프롬프트가
    "define function `set`"이 됐고, v2 정적 검증이 이를 강제해 짝 비교 2패를 만들었음 — AUDIT.md N2)
    """
    tests = list(tests)
    defs = re.findall(r"^def\s+([A-Za-z_]\w*)\s*\(", code, re.M)
    called = [n for t in tests for n in re.findall(r"([A-Za-z_]\w*)\s*\(", t)]
    for name in called:  # 테스트가 실제 호출하는 def가 진입점
        if name in defs:
            return name
    if defs:
        return defs[-1]
    for name in called:  # 참조 코드 없을 때: builtin이 아닌 첫 호출 식별자
        if name not in BUILTIN_NAMES:
            return name
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
        entry = _infer_entry_point_from_tests(tests, item.get("code", ""))
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
    return _extract_code_with_label(output, task)[0]


def _extract_code_with_label(output: str, task: ExternalTask) -> tuple[str, str]:
    """(채점용 코드, 추출 방식). 추출 방식은 결과 행에 남긴다 — raw 는 산출물이 아니라 출력 전체가 채점됐다는 뜻."""
    blocks = re.findall(r"```(?:python|py)?\s*(.*?)```", output, flags=re.I | re.S)
    if blocks:
        preferred = [b for b in blocks if f"def {task.entry_point}" in b]
        code = max(preferred or blocks, key=len).strip()
        extraction = "fenced"
    else:
        marker = f"def {task.entry_point}"
        if marker in output:
            code = output[output.index(marker) :].strip()
            extraction = "heuristic"
        else:
            match = re.search(r"(^|\n)(from\s+\S+\s+import\s+|import\s+|def\s+)", output)
            code = output[match.start() :].strip() if match else output.strip()
            extraction = "heuristic" if match else "raw"

    code = code.replace("\r\n", "\n")
    if f"def {task.entry_point}" not in code and task.humaneval_prefix:
        code = f"{task.humaneval_prefix.rstrip()}\n{code}"
        extraction += "+prefix"     # HumanEval 프롬프트의 함수 머리를 앞에 붙여 완성한 경우
    return f"{COMMON_PREAMBLE}\n\n{code}\n", extraction


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


def _visible_tests(task: ExternalTask) -> List[str]:
    """루프 안(validator)이 볼 수 있는 공개 테스트.
    HumanEval: docstring 의 >>> 예제를 doctest 로 뽑아 assert 로 변환. MBPP: 프롬프트에 노출된 test_list (공개)."""
    if task.benchmark == "humaneval":
        import doctest
        out = []
        for ex in doctest.DocTestParser().get_examples(task.humaneval_prefix or ""):
            src, want = ex.source.strip(), ex.want.strip()
            if not want or "\n" in src:
                continue                       # 출력 없는 예제(설정 문장)나 여러 줄 소스는 건너뜀
            out.append(f"_r = ({src})\nassert repr(_r) == {want!r}, ('expected', {want!r}, 'got', repr(_r))")
        return out
    return [t for t in task.tests.splitlines() if t.strip()]


def _hidden_tests(task: ExternalTask) -> List[str]:
    """사후 채점 테스트. HumanEval: check(entry_point) 호출까지 포함한 프로그램 1건.
    MBPP: 채점 테스트가 곧 공개 test_list — 히든이 아니다 (hidden_exposed=True 로 표시, EvalPlus 승인 전까지 공개 검증용)."""
    if task.benchmark == "humaneval":
        return [f"{task.test_setup}\n\n{task.tests}\n\ncheck({task.entry_point})\n"]
    return [f"{task.test_setup}\n\n{t}" if task.test_setup else t for t in task.tests.splitlines() if t.strip()]


def _task_spec(task: ExternalTask) -> Dict[str, Any]:
    return {"kind": "code", "entry_point": task.entry_point, "tests": _visible_tests(task),
            "hidden_tests": _hidden_tests(task), "hidden_exposed": task.benchmark != "humaneval"}


def evaluate_code(code: str, task: ExternalTask, timeout_s: float) -> tuple[bool, str, Dict[str, Any]]:
    """사후 채점 = verify.score_hidden (하네스 result.json + nonce). 종료 코드는 보지 않는다 (A7c)."""
    from harmonet.verify import score_hidden
    safety = _safety_error(code)
    if safety:
        return False, safety, {"outcome": "error", "level": "static", "passed": False, "evidence": safety}
    r = score_hidden(code, _task_spec(task), timeout_s=timeout_s)
    err = "" if r["passed"] else f"{r['outcome']}: {r['evidence'][-600:]}"
    return r["passed"], err, r


def evaluate_code_exitcode_legacy(code: str, task: ExternalTask, timeout_s: float) -> tuple[bool, str]:
    """구 채점기 (2026-09-13 이전): 종료 코드 0 = 통과. **대조용으로만 보존** (RESCORE.md). 새 코드는 쓰지 않는다."""
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
        # validator 기계 검증 명세: 공개 테스트(HumanEval doctest / MBPP 공개 test_list)만. hidden_tests 는 넘기지 않는다.
        spec={"kind": "code", "entry_point": task.entry_point, "tests": _visible_tests(task)},
    )


def _run_one(adapter: Any, task: ExternalTask, repeat: int, timeout_s: float) -> ExternalMeasurement:
    t0 = time.perf_counter()
    prompt_tokens = completion_tokens = total_tokens = 0
    output = ""
    metadata: Dict[str, Any] = {}
    eval_error = ""
    passed = False
    code, extraction, score = "", "", {}

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
        code, extraction = _extract_code_with_label(output, task)
        passed, eval_error, score = evaluate_code(code, task, timeout_s)
        # eval-repair 는 채점기의 실패 출력을 생성 프롬프트에 넣는다 (히든 테스트 누출). 기본 차단.
        # 켜려면 G1_DISABLE_EVAL_REPAIR=0 을 명시 — 그 실행의 trace 는 leak_risk=true 로 라벨된다.
        if (
            not passed
            and hasattr(adapter, "repair_after_eval")
            and os.getenv("G1_DISABLE_EVAL_REPAIR", "1").lower() in ("0", "false", "no")
        ):
            repair_started = time.perf_counter()
            repair = adapter.repair_after_eval(_to_benchmark_task(task), output, eval_error)
            repaired_output = str(repair.get("output", ""))
            repaired_code, repaired_extraction = _extract_code_with_label(repaired_output, task)
            repaired_passed, repaired_error, repaired_score = evaluate_code(repaired_code, task, timeout_s)
            prompt_tokens += int(repair.get("prompt_tokens", 0) or 0)
            completion_tokens += int(repair.get("completion_tokens", 0) or 0)
            total_tokens = prompt_tokens + completion_tokens
            metadata["eval_repair"] = dict(repair.get("metadata", {}))
            metadata["eval_repair"]["latency_s"] = round(time.perf_counter() - repair_started, 4)
            if repaired_passed:
                output = repaired_output
                code, extraction, score = repaired_code, repaired_extraction, repaired_score
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
        extracted_chars=len(code),
        metadata=metadata,
        candidate_code=code,
        extraction=extraction,
        outcome=str(score.get("outcome", "")),
        hidden_exposed=task.benchmark != "humaneval",
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
    """pass_rate = **히든** 통과율 (hidden_exposed=False 행만; 가드가 검사).
    노출 행(MBPP)은 public_satisfaction_rate 로 따로 집계 — 두 지표를 합치지 않는다 (C3b)."""
    from benchmark.hidden_guard import hidden_pass_rate, public_satisfaction_rate, split_by_exposure
    hidden_rows, exposed_rows = split_by_exposure(measurements)
    passed = [1.0 if m.passed else 0.0 for m in hidden_rows]
    tokens = [float(m.total_tokens) for m in measurements]
    latencies = [float(m.latency_seconds) for m in measurements]
    return {
        "system": system,
        "runs": len(measurements),
        "hidden_runs": len(hidden_rows),
        "pass_rate": round(hidden_pass_rate(hidden_rows, system), 4) if hidden_rows else None,
        "pass_rate_ci95": round(_ci95(passed), 4) if hidden_rows else None,
        "exposed_runs": len(exposed_rows),
        "public_satisfaction_rate": round(public_satisfaction_rate(exposed_rows), 4) if exposed_rows else None,
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
        pr = f"{s['pass_rate']*100:>6.1f}%+/-{s['pass_rate_ci95']*100:<4.1f}" if s["pass_rate"] is not None else f"{'n/a(hidden)':>12}"
        ps = f" public={s['public_satisfaction_rate']*100:.1f}%({s['exposed_runs']})" if s["public_satisfaction_rate"] is not None else ""
        lines.append(
            f"{name:<58} "
            f"{pr} "
            f"{s['avg_total_tokens']:>10.0f} "
            f"{s['avg_latency_s']:>9.2f} "
            f"{s['p99_latency_s']:>8.2f}{ps}"
        )

    harmonet = next((s for n, s in summaries.items() if n == "harmonet"), None)
    langraph = next((s for n, s in summaries.items() if "langraph" in n), None)
    if harmonet and langraph and harmonet["pass_rate"] is not None and langraph["pass_rate"] is not None:
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
                metric = (f"hidden_pass={s['pass_rate']*100:5.1f}%" if s["pass_rate"] is not None
                          else f"public_sat={s['public_satisfaction_rate']*100:5.1f}%")
                lines.append(
                    f"    {name:<54} {metric} "
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
            "outcome",
            "extraction",
            "hidden_exposed",
            "candidate_code",
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
                    m.outcome,
                    m.extraction,
                    m.hidden_exposed,
                    m.candidate_code,
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
    # 임베딩을 쓰는 어댑터(v1, 그리고 v1 폴백이 가능한 v2)가 있으면 실행 전 건전성 게이트.
    # 난수 임베딩 위에서 돌린 결과가 다시는 나오지 않게 함 (AUDIT.md N1).
    if any(a in ("harmonet", "harmonet_v2") for a in adapter_names) and not args.skip_harmonet:
        from harmonet.embed import assert_embedding_sane

        assert_embedding_sane()
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
