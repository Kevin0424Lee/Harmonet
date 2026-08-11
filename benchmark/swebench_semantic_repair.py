"""
SWE-bench semantic repair runner.

Takes an evaluated SWE-bench prediction file plus official harness logs,
selects unresolved instances, and asks an adapter to regenerate a replacement
patch using failing test output as feedback.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.tasks import BenchmarkTask
from benchmark.swebench_g1 import (
    _adapter,
    _check_patch_applies,
    _clean_patch,
    _ensure_repo,
    _extract_patch,
    _make_prompt,
    _make_repair_prompt,
    _normalize_patch,
    _patch_files,
    _prediction_record,
)


@dataclass
class SemanticRepairMeasurement:
    instance_id: str
    system: str
    attempted: bool
    selected: bool
    original_patch_chars: int
    repaired_patch_chars: int
    patch_applies: bool
    kept_original: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    failing_tests: int
    error: str = ""
    apply_error: str = ""


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_dataset_map(dataset_name: str, split: str) -> Dict[str, Dict[str, Any]]:
    from datasets import load_dataset

    return {item["instance_id"]: item for item in load_dataset(dataset_name, split=split)}


def _read_text(path: Path, max_chars: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _instance_report(log_root: Path, instance_id: str) -> Dict[str, Any]:
    report_path = log_root / instance_id / "report.json"
    if not report_path.exists():
        return {}
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return payload.get(instance_id, payload)


def _failing_tests(report: Dict[str, Any]) -> List[str]:
    tests_status = report.get("tests_status") or {}
    failures: List[str] = []
    for group in ["FAIL_TO_PASS", "PASS_TO_FAIL", "FAIL_TO_FAIL"]:
        group_payload = tests_status.get(group) or {}
        for test_name in group_payload.get("failure") or []:
            failures.append(f"{group}: {test_name}")
    return failures


def _make_semantic_prompt(
    original_prompt: str,
    previous_patch: str,
    failing_tests: List[str],
    test_output: str,
    report: Dict[str, Any],
) -> str:
    patch_excerpt = previous_patch[:16000] + ("\n...[patch truncated]...\n" if len(previous_patch) > 16000 else "")
    tests_excerpt = "\n".join(failing_tests[:80]) or "No failing test names were extracted."
    report_excerpt = json.dumps(report, indent=2, ensure_ascii=False)[:12000]
    return (
        f"{original_prompt}\n\n"
        "The previous patch applied cleanly but failed the official SWE-bench tests.\n"
        "Regenerate a complete replacement patch against the original base commit.\n"
        "Do not output an incremental patch on top of the previous patch.\n"
        "Return only a valid unified diff. Do not explain. Do not use markdown fences.\n\n"
        "Previous patch:\n"
        f"```diff\n{patch_excerpt}\n```\n\n"
        "Failing tests:\n"
        f"```text\n{tests_excerpt}\n```\n\n"
        "Official per-instance report excerpt:\n"
        f"```json\n{report_excerpt}\n```\n\n"
        "Tail of official test output:\n"
        f"```text\n{test_output}\n```\n"
    )


def _selected_ids(report_path: Path, include_empty: bool) -> List[str]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ids = list(report.get("unresolved_ids") or [])
    if include_empty:
        ids.extend(report.get("empty_patch_ids") or [])
    seen = set()
    ordered = []
    for instance_id in ids:
        if instance_id not in seen:
            seen.add(instance_id)
            ordered.append(instance_id)
    return ordered


def _write_outputs(
    output_path: Path,
    metrics_path: Path,
    predictions: List[Dict[str, Any]],
    measurements: List[SemanticRepairMeasurement],
) -> None:
    output_path.write_text(
        "\n".join(json.dumps(row) for row in predictions) + "\n",
        encoding="utf-8",
    )
    with metrics_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(SemanticRepairMeasurement.__dataclass_fields__.keys()))
        writer.writeheader()
        for measurement in measurements:
            writer.writerow(asdict(measurement))


def run(args: argparse.Namespace) -> int:
    adapter = _adapter(args.adapter)
    system_name = args.name or f"{adapter.name}_semantic"
    predictions = _load_jsonl(Path(args.predictions))
    prediction_by_id = {row["instance_id"]: row for row in predictions}
    dataset_by_id = _load_dataset_map(args.dataset_name, args.split)
    selected = _selected_ids(Path(args.eval_report), args.include_empty)
    if args.limit:
        selected = selected[: args.limit]

    cache_dir = Path(args.repo_cache)
    log_root = Path(args.log_root)
    output_path = Path(args.output)
    metrics_path = output_path.with_suffix(".metrics.csv")
    measurements: List[SemanticRepairMeasurement] = []

    print(f"Semantic repair selected={len(selected)} adapter={system_name}")
    for idx, instance_id in enumerate(selected, 1):
        t0 = time.perf_counter()
        original_row = prediction_by_id.get(instance_id)
        instance = dataset_by_id.get(instance_id)
        previous_patch = (original_row or {}).get("model_patch", "")
        prompt_tokens = 0
        completion_tokens = 0
        repaired_patch = ""
        patch_applies = False
        kept_original = False
        apply_error = ""
        error = ""
        report = _instance_report(log_root, instance_id)
        failing_tests = _failing_tests(report)

        try:
            if not original_row:
                raise RuntimeError("instance missing from prediction file")
            if not instance:
                raise RuntimeError("instance missing from dataset")
            if not previous_patch.strip() and not args.include_empty:
                raise RuntimeError("empty previous patch")

            repo_dir = _ensure_repo(instance["repo"], cache_dir, instance["base_commit"])
            original_prompt = _make_prompt(
                instance,
                repo_dir,
                max_file_chars=args.max_file_chars,
                max_total_context=args.max_total_context,
            )
            test_output = _read_text(log_root / instance_id / "test_output.txt", args.max_test_output_chars)
            task = BenchmarkTask(
                id=f"{instance_id}_semantic_repair",
                category="swebench_semantic",
                prompt=_make_semantic_prompt(original_prompt, previous_patch, failing_tests, test_output, report),
                expected_keywords=["diff --git"] + _patch_files(instance.get("patch", "")),
                complexity=4,
            )
            result = adapter.run(task)
            prompt_tokens += int(result.get("prompt_tokens", 0) or 0)
            completion_tokens += int(result.get("completion_tokens", 0) or 0)
            repaired_patch = _extract_patch(str(result.get("output", "")))
            repaired_patch = _normalize_patch(_clean_patch(repaired_patch)) if repaired_patch else ""

            if repaired_patch:
                patch_applies, apply_error = _check_patch_applies(
                    repo_dir,
                    instance["base_commit"],
                    repaired_patch,
                    timeout=args.apply_timeout,
                )

            repair_attempt = 0
            while repaired_patch and not patch_applies and repair_attempt < args.format_repair_attempts:
                repair_attempt += 1
                repair_task = BenchmarkTask(
                    id=f"{instance_id}_semantic_format_repair_{repair_attempt}",
                    category="swebench_semantic",
                    prompt=_make_repair_prompt(original_prompt, repaired_patch, apply_error, "hunk_failed"),
                    expected_keywords=["diff --git"] + _patch_files(instance.get("patch", "")),
                    complexity=4,
                )
                repair_result = adapter.run(repair_task)
                prompt_tokens += int(repair_result.get("prompt_tokens", 0) or 0)
                completion_tokens += int(repair_result.get("completion_tokens", 0) or 0)
                repaired_patch = _extract_patch(str(repair_result.get("output", "")))
                repaired_patch = _normalize_patch(_clean_patch(repaired_patch)) if repaired_patch else ""
                if not repaired_patch:
                    break
                patch_applies, apply_error = _check_patch_applies(
                    repo_dir,
                    instance["base_commit"],
                    repaired_patch,
                    timeout=args.apply_timeout,
                )

            if patch_applies:
                prediction_by_id[instance_id] = _prediction_record(instance_id, system_name, repaired_patch)
            else:
                kept_original = args.keep_original_on_failure
                if not kept_original:
                    prediction_by_id[instance_id] = _prediction_record(instance_id, system_name, "")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            kept_original = args.keep_original_on_failure

        elapsed = time.perf_counter() - t0
        measurements.append(
            SemanticRepairMeasurement(
                instance_id=instance_id,
                system=system_name,
                attempted=not bool(error),
                selected=True,
                original_patch_chars=len(previous_patch),
                repaired_patch_chars=len(repaired_patch),
                patch_applies=patch_applies,
                kept_original=kept_original,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_seconds=round(elapsed, 4),
                failing_tests=len(failing_tests),
                error=error,
                apply_error=apply_error,
            )
        )
        status = "REPAIRED" if patch_applies else ("KEPT" if kept_original else "EMPTY")
        print(f"[{system_name}] {idx}/{len(selected)} {instance_id} {status} {prompt_tokens + completion_tokens}tok {elapsed:.1f}s")

    output_rows = []
    for row in predictions:
        instance_id = row["instance_id"]
        output_rows.append(prediction_by_id.get(instance_id, row))
    _write_outputs(output_path, metrics_path, output_rows, measurements)
    print(f"Saved semantic predictions: {output_path}")
    print(f"Saved semantic metrics: {metrics_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair SWE-bench predictions from official test failures.")
    parser.add_argument("--dataset-name", default="SWE-bench/SWE-bench_Lite")
    parser.add_argument("--split", default="test")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--eval-report", required=True)
    parser.add_argument("--log-root", required=True)
    parser.add_argument("--adapter", default="harmonet", choices=["harmonet", "harmonet_v2", "langraph", "autogen", "crewai"])
    parser.add_argument("--name", default="")
    parser.add_argument("--output", default="swebench_g1_semantic_repaired.jsonl")
    parser.add_argument("--repo-cache", default="swebench_repo_cache")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--include-empty", action="store_true")
    parser.add_argument("--max-file-chars", type=int, default=12000)
    parser.add_argument("--max-total-context", type=int, default=36000)
    parser.add_argument("--max-test-output-chars", type=int, default=18000)
    parser.add_argument("--apply-timeout", type=int, default=180)
    parser.add_argument("--format-repair-attempts", type=int, default=1)
    parser.add_argument("--keep-original-on-failure", action="store_true", default=True)
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
