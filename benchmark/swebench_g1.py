"""
SWE-bench Lite G1 prediction generator.

This module creates SWE-bench-compatible JSONL predictions:

    {"instance_id": "...", "model_name_or_path": "...", "model_patch": "..."}

The official SWE-bench harness performs evaluation separately with
`python -m swebench.harness.run_evaluation`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from benchmark.tasks import BenchmarkTask


PATCH_RE = re.compile(r"diff --git a/(.*?) b/(.*?)(?:\n|$)")


@dataclass
class Sweeprediction:
    instance_id: str
    system: str
    passed_generation: bool
    patch_applies: bool
    initial_patch_applies: bool
    valid_after_repair: bool
    dropped_invalid: bool
    repair_attempts: int
    malformed_repairs: int
    hunk_repairs: int
    other_repairs: int
    failure_kind: str
    repair_modes: List[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    patch_chars: int
    changed_files: List[str]
    error: str = ""
    apply_error: str = ""


def _run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return proc.stdout


def _run_check(
    cmd: List[str],
    cwd: Optional[Path] = None,
    input_text: Optional[str] = None,
    timeout: int = 120,
) -> Tuple[bool, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    return proc.returncode == 0, output.strip()


def _patch_files(patch: str) -> List[str]:
    files = []
    for left, right in PATCH_RE.findall(patch or ""):
        files.append(right or left)
    return sorted(set(files))


def _ensure_repo(repo: str, cache_dir: Path, base_commit: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = cache_dir / repo.replace("/", "__")
    url = f"https://github.com/{repo}.git"
    if not repo_dir.exists():
        _run(["git", "clone", "--no-checkout", "--filter=blob:none", url, str(repo_dir)], timeout=600)
    ok, output = _run_check(["git", "fetch", "--depth", "1", "origin", base_commit], cwd=repo_dir, timeout=600)
    if not ok:
        ok, output = _run_check(["git", "fetch", "origin", base_commit], cwd=repo_dir, timeout=600)
    if not ok:
        raise RuntimeError(("git fetch failed:\n" + output)[-4000:])
    return repo_dir


def _show_file(repo_dir: Path, base_commit: str, file_path: str, max_chars: int) -> str:
    try:
        content = _run(["git", "show", f"{base_commit}:{file_path}"], cwd=repo_dir, timeout=60)
    except Exception as exc:
        return f"[Could not read {file_path}: {exc}]"
    if len(content) > max_chars:
        return content[:max_chars] + "\n...[truncated]...\n"
    return content


def _extract_patch(output: str) -> str:
    output = output or ""
    blocks = re.findall(r"```(?:diff|patch)?\s*(diff --git.*?)```", output, flags=re.I | re.S)
    if blocks:
        return _clean_patch(max(blocks, key=len))
    idx = output.find("diff --git")
    if idx >= 0:
        return _clean_patch(output[idx:])
    return ""


def _clean_patch(patch: str) -> str:
    patch = patch.replace("\r\n", "\n").strip()
    patch = re.split(r"\n---\s*(?:\n|$)", patch, maxsplit=1)[0].strip()
    return _normalize_patch(patch)


def _normalize_patch(patch: str) -> str:
    patch = (patch or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not patch:
        return ""

    idx = patch.find("diff --git")
    if idx >= 0:
        patch = patch[idx:]

    allowed_meta = (
        "diff --git ",
        "index ",
        "--- ",
        "+++ ",
        "new file mode ",
        "deleted file mode ",
        "old mode ",
        "new mode ",
        "similarity index ",
        "dissimilarity index ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
    )
    normalized: List[str] = []
    in_hunk = False
    for raw_line in patch.split("\n"):
        line = raw_line.rstrip("\n")
        if line.startswith("diff --git "):
            in_hunk = False
            normalized.append(line)
            continue
        if line.startswith("@@"):
            in_hunk = True
            normalized.append(line)
            continue
        if in_hunk:
            if line.startswith((" ", "+", "-", "\\")):
                normalized.append(line)
            elif line == "":
                normalized.append(" ")
            else:
                normalized.append(" " + line)
            continue
        if line.startswith(allowed_meta):
            in_hunk = False
            normalized.append(line)
            continue

    return _recount_hunks("\n".join(normalized).strip() + "\n") if normalized else ""


def _recount_hunks(patch: str) -> str:
    lines = patch.splitlines()
    out: List[str] = []
    i = 0
    hunk_re = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)")

    while i < len(lines):
        line = lines[i]
        match = hunk_re.match(line)
        if not match:
            out.append(line)
            i += 1
            continue

        old_start = int(match.group(1))
        new_start = int(match.group(2))
        suffix = match.group(3)
        hunk_lines: List[str] = []
        i += 1
        while i < len(lines) and not lines[i].startswith(("diff --git ", "@@ ")):
            hunk_lines.append(lines[i])
            i += 1

        old_count = 0
        new_count = 0
        for hunk_line in hunk_lines:
            if hunk_line.startswith("\\"):
                continue
            if hunk_line.startswith((" ", "-")):
                old_count += 1
            if hunk_line.startswith((" ", "+")):
                new_count += 1

        out.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}")
        out.extend(hunk_lines)

    return "\n".join(out).strip() + "\n" if out else ""


def _classify_apply_error(error: str) -> str:
    lowered = (error or "").lower()
    if not lowered:
        return "none"
    if any(marker in lowered for marker in ["malformed patch", "corrupt patch", "without header", "패치가", "헤더 없는"]):
        return "malformed"
    if any(marker in lowered for marker in ["patch failed", "does not apply", "패치 실패"]):
        return "hunk_failed"
    if "empty patch" in lowered:
        return "empty"
    return "other"


def _failed_locations(apply_error: str) -> List[Tuple[str, Optional[int]]]:
    locations: List[Tuple[str, Optional[int]]] = []
    patterns = [
        r"(?:patch failed|패치 실패):\s*([^:\n]+):(\d+)",
        r"error:\s*([^:\n]+):(\d+):",
        r"checking file\s+([^\n]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, apply_error or "", flags=re.I):
            path = match.group(1).strip()
            line_no = int(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2).isdigit() else None
            if path and (path, line_no) not in locations:
                locations.append((path, line_no))
    return locations


def _show_file_window(
    repo_dir: Path,
    base_commit: str,
    file_path: str,
    line_no: Optional[int],
    radius: int,
    max_chars: int,
) -> str:
    try:
        content = _run(["git", "show", f"{base_commit}:{file_path}"], cwd=repo_dir, timeout=60)
    except Exception as exc:
        return f"[Could not read {file_path}: {exc}]"

    lines = content.splitlines()
    if not lines:
        return "[empty file]"
    if line_no is None:
        start = 1
        end = min(len(lines), radius * 2)
    else:
        start = max(1, line_no - radius)
        end = min(len(lines), line_no + radius)

    rendered = "\n".join(f"{idx:6d}: {lines[idx - 1]}" for idx in range(start, end + 1))
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars] + "\n...[context truncated]..."
    return rendered


def _patch_excerpt_for_file(patch: str, file_path: str, max_chars: int = 8000) -> str:
    chunks = re.split(r"(?=^diff --git )", patch or "", flags=re.M)
    for chunk in chunks:
        if f" b/{file_path}" in chunk or f" a/{file_path}" in chunk:
            return chunk[:max_chars]
    return (patch or "")[:max_chars]


def _make_failure_context(
    repo_dir: Path,
    base_commit: str,
    patch: str,
    apply_error: str,
    context_lines: int,
    max_chars: int,
) -> str:
    locations = _failed_locations(apply_error)
    if not locations:
        locations = [(path, None) for path in _patch_files(patch)[:2]]

    blocks = []
    for path, line_no in locations[:3]:
        source = _show_file_window(repo_dir, base_commit, path, line_no, context_lines, max_chars)
        failed_patch = _patch_excerpt_for_file(patch, path, max_chars=max_chars)
        blocks.append(
            f"\n### Failed file: {path}\n"
            f"Approx failed line: {line_no if line_no is not None else 'unknown'}\n"
            "Base source context with line numbers:\n"
            f"```text\n{source}\n```\n"
            "Previous diff excerpt for this file:\n"
            f"```diff\n{failed_patch}\n```\n"
        )
    return "\n".join(blocks)


def _check_patch_applies(repo_dir: Path, base_commit: str, patch: str, timeout: int) -> Tuple[bool, str]:
    if not patch.strip():
        return False, "empty patch"

    with tempfile.TemporaryDirectory(prefix="swebench_apply_", dir=str(repo_dir.parent)) as tmp:
        worktree = Path(tmp) / "worktree"
        ok, output = _run_check(
            ["git", "worktree", "add", "--detach", "--force", str(worktree), base_commit],
            cwd=repo_dir,
            timeout=timeout,
        )
        if not ok:
            return False, ("git worktree add failed:\n" + output)[-4000:]

        try:
            ok, output = _run_check(
                ["git", "apply", "--check", "--whitespace=nowarn", "-"],
                cwd=worktree,
                input_text=patch,
                timeout=timeout,
            )
            return ok, output[-4000:]
        finally:
            _run_check(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=repo_dir,
                timeout=timeout,
            )


def _make_prompt(instance: Dict[str, Any], repo_dir: Path, max_file_chars: int, max_total_context: int) -> str:
    files = _patch_files(instance.get("patch", ""))
    chunks = []
    total = 0
    for path in files:
        content = _show_file(repo_dir, instance["base_commit"], path, max_file_chars)
        block = f"\n### File: {path}\n```python\n{content}\n```\n"
        if total + len(block) > max_total_context:
            break
        chunks.append(block)
        total += len(block)

    file_list = "\n".join(f"- {p}" for p in files) or "- unknown"
    hints = instance.get("hints_text") or ""
    return (
        "You are generating a SWE-bench prediction patch.\n"
        "Return only a valid unified diff. Do not use markdown fences. Do not explain.\n"
        "The diff must use paths exactly like `diff --git a/path b/path`.\n\n"
        f"Repository: {instance['repo']}\n"
        f"Base commit: {instance['base_commit']}\n"
        f"Instance: {instance['instance_id']}\n\n"
        f"Issue:\n{instance['problem_statement']}\n\n"
        f"Hints:\n{hints}\n\n"
        "Relevant file paths from oracle retrieval:\n"
        f"{file_list}\n"
        f"{''.join(chunks)}\n"
        "Return the minimal patch that fixes the issue."
    )


def _make_repair_prompt(
    original_prompt: str,
    patch: str,
    apply_error: str,
    failure_kind: str,
    failure_context: str = "",
) -> str:
    patch_excerpt = patch if len(patch) <= 12000 else patch[:12000] + "\n...[patch truncated]...\n"
    error_excerpt = apply_error[-5000:]
    if failure_kind == "malformed":
        instruction = (
            "The previous diff is syntactically invalid. Fix unified diff format and hunk counts.\n"
            "Every hunk line must start with exactly one of: space, +, -, or backslash.\n"
            "Do not invent new files unless required by the issue."
        )
    elif failure_kind == "hunk_failed":
        instruction = (
            "The previous diff hunk does not match the base commit. Regenerate the patch using the exact base source context below.\n"
            "Prefer smaller hunks with accurate surrounding context. Do not reuse stale line context."
        )
    else:
        instruction = "The previous diff was not accepted. Return a corrected unified diff."

    return (
        f"{original_prompt}\n\n"
        "The previous answer was not accepted by `git apply --check`.\n"
        "Return only a corrected unified diff. Do not explain. Do not use markdown fences.\n\n"
        f"{instruction}\n\n"
        "Previous diff:\n"
        f"{patch_excerpt}\n\n"
        "`git apply --check` error:\n"
        f"{error_excerpt}\n\n"
        f"{failure_context}\n"
    )


def _adapter(name: str):
    if name == "harmonet":
        from benchmark.agents_harmonet import HarmoNetAdapter

        return HarmoNetAdapter(ticks=int(os.getenv("SWE_G1_HARMONET_TICKS", "2")))
    if name == "harmonet_v2":
        from benchmark.agents_harmonet_v2 import HarmoNetV2Adapter

        return HarmoNetV2Adapter(ticks=int(os.getenv("SWE_G1_HARMONET_TICKS", "2")))
    if name == "langraph":
        from benchmark.agents_langraph import LangGraphAdapter

        return LangGraphAdapter()
    if name == "autogen":
        from benchmark.agents_autogen import AutoGenAdapter

        return AutoGenAdapter()
    if name == "crewai":
        from benchmark.agents_crewai import CrewAIAdapter

        return CrewAIAdapter()
    raise ValueError(f"Unknown adapter: {name}")


def _prediction_record(instance_id: str, model_name: str, patch: str) -> Dict[str, str]:
    return {
        "instance_id": instance_id,
        "model_name_or_path": model_name,
        "model_patch": patch,
    }


def generate(args: argparse.Namespace) -> int:
    from datasets import load_dataset

    dataset = list(load_dataset(args.dataset_name, split=args.split))
    selected = dataset[args.offset : args.offset + args.limit if args.limit else None]
    adapter = _adapter(args.adapter)
    system_name = args.name or adapter.name

    out_path = Path(args.output)
    metrics_path = out_path.with_suffix(".metrics.csv")
    cache_dir = Path(args.repo_cache)

    existing = set()
    if out_path.exists() and not args.overwrite:
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.loads(line)["instance_id"])

    mode = "w" if args.overwrite else "a"
    measurements: List[Sweeprediction] = []
    with out_path.open(mode, encoding="utf-8") as pred_f:
        for index, instance in enumerate(selected, 1):
            instance_id = instance["instance_id"]
            if instance_id in existing:
                print(f"[{system_name}] {index}/{len(selected)} {instance_id} skip")
                continue

            t0 = time.perf_counter()
            patch = ""
            result: Dict[str, Any] = {}
            error = ""
            apply_error = ""
            patch_applies = False
            initial_patch_applies = False
            valid_after_repair = False
            dropped_invalid = False
            failure_kind = "none"
            repair_attempts = 0
            malformed_repairs = 0
            hunk_repairs = 0
            other_repairs = 0
            repair_modes: List[str] = []
            prompt_tokens = 0
            completion_tokens = 0
            try:
                repo_dir = _ensure_repo(instance["repo"], cache_dir, instance["base_commit"])
                prompt = _make_prompt(
                    instance,
                    repo_dir,
                    max_file_chars=args.max_file_chars,
                    max_total_context=args.max_total_context,
                )
                task = BenchmarkTask(
                    id=instance_id,
                    category="swebench",
                    prompt=prompt,
                    expected_keywords=["diff --git"] + _patch_files(instance.get("patch", "")),
                    complexity=3,
                )
                result = adapter.run(task)
                prompt_tokens += int(result.get("prompt_tokens", 0) or 0)
                completion_tokens += int(result.get("completion_tokens", 0) or 0)
                patch = _extract_patch(str(result.get("output", "")))
                if args.validate_patches:
                    patch_applies, apply_error = _check_patch_applies(
                        repo_dir,
                        instance["base_commit"],
                        patch,
                        timeout=args.apply_timeout,
                    )
                    initial_patch_applies = patch_applies
                    while patch and not patch_applies:
                        failure_kind = _classify_apply_error(apply_error)
                        if failure_kind == "malformed":
                            if malformed_repairs >= args.malformed_repair_attempts:
                                break
                            malformed_repairs += 1
                        elif failure_kind == "hunk_failed":
                            if hunk_repairs >= args.hunk_repair_attempts:
                                break
                            hunk_repairs += 1
                        else:
                            if other_repairs >= args.repair_attempts:
                                break
                            other_repairs += 1

                        repair_attempts += 1
                        repair_modes.append(failure_kind)
                        failure_context = ""
                        if failure_kind == "hunk_failed":
                            failure_context = _make_failure_context(
                                repo_dir,
                                instance["base_commit"],
                                patch,
                                apply_error,
                                context_lines=args.hunk_context_lines,
                                max_chars=args.repair_context_chars,
                            )
                        repair_task = BenchmarkTask(
                            id=f"{instance_id}_repair_{repair_attempts}",
                            category="swebench",
                            prompt=_make_repair_prompt(prompt, patch, apply_error, failure_kind, failure_context),
                            expected_keywords=["diff --git"] + _patch_files(instance.get("patch", "")),
                            complexity=3,
                        )
                        repair_result = adapter.run(repair_task)
                        prompt_tokens += int(repair_result.get("prompt_tokens", 0) or 0)
                        completion_tokens += int(repair_result.get("completion_tokens", 0) or 0)
                        repaired_patch = _extract_patch(str(repair_result.get("output", "")))
                        if not repaired_patch:
                            apply_error = ("repair attempt returned no diff\n" + apply_error)[-5000:]
                            break
                        patch = _normalize_patch(repaired_patch)
                        patch_applies, apply_error = _check_patch_applies(
                            repo_dir,
                            instance["base_commit"],
                            patch,
                            timeout=args.apply_timeout,
                        )
                    failure_kind = _classify_apply_error(apply_error) if not patch_applies else "none"
                    valid_after_repair = patch_applies and not initial_patch_applies
                    if args.drop_invalid and not patch_applies:
                        patch = ""
                        dropped_invalid = True
                else:
                    patch_applies = bool(patch)
                    initial_patch_applies = patch_applies
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            elapsed = time.perf_counter() - t0
            pred_f.write(json.dumps(_prediction_record(instance_id, system_name, patch)) + "\n")
            pred_f.flush()

            measurement = Sweeprediction(
                instance_id=instance_id,
                system=system_name,
                passed_generation=bool(patch),
                patch_applies=patch_applies,
                initial_patch_applies=initial_patch_applies,
                valid_after_repair=valid_after_repair,
                dropped_invalid=dropped_invalid,
                repair_attempts=repair_attempts,
                malformed_repairs=malformed_repairs,
                hunk_repairs=hunk_repairs,
                other_repairs=other_repairs,
                failure_kind=failure_kind,
                repair_modes=repair_modes,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_seconds=round(elapsed, 4),
                patch_chars=len(patch),
                changed_files=_patch_files(instance.get("patch", "")),
                error=error,
                apply_error=apply_error,
            )
            measurements.append(measurement)
            if not patch:
                status = "EMPTY"
            elif args.validate_patches:
                status = "VALID_REPAIR" if valid_after_repair else ("VALID" if patch_applies else "INVALID")
            else:
                status = "PATCH"
            print(f"[{system_name}] {index}/{len(selected)} {instance_id} {status} {measurement.total_tokens}tok {elapsed:.1f}s")

    write_header = not metrics_path.exists() or args.overwrite
    with metrics_path.open("w" if args.overwrite else "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(measurements[0]).keys()) if measurements else list(Sweeprediction.__dataclass_fields__.keys()))
        if write_header:
            writer.writeheader()
        for measurement in measurements:
            row = asdict(measurement)
            row["changed_files"] = ";".join(row["changed_files"])
            row["repair_modes"] = ";".join(row["repair_modes"])
            writer.writerow(row)

    print(f"Saved predictions: {out_path}")
    print(f"Saved generation metrics: {metrics_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SWE-bench Lite G1 predictions.")
    parser.add_argument("--dataset-name", default="SWE-bench/SWE-bench_Lite")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--adapter", default="harmonet", choices=["harmonet", "harmonet_v2", "langraph", "autogen", "crewai"])
    parser.add_argument("--name", default="")
    parser.add_argument("--output", default="swebench_g1_predictions.jsonl")
    parser.add_argument("--repo-cache", default="swebench_repo_cache")
    parser.add_argument("--max-file-chars", type=int, default=12000)
    parser.add_argument("--max-total-context", type=int, default=36000)
    parser.add_argument("--no-validate-patches", dest="validate_patches", action="store_false")
    parser.add_argument("--repair-attempts", type=int, default=1)
    parser.add_argument("--malformed-repair-attempts", type=int, default=2)
    parser.add_argument("--hunk-repair-attempts", type=int, default=1)
    parser.add_argument("--hunk-context-lines", type=int, default=80)
    parser.add_argument("--repair-context-chars", type=int, default=12000)
    parser.add_argument("--apply-timeout", type=int, default=180)
    parser.add_argument("--drop-invalid", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.set_defaults(validate_patches=True)
    return generate(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
