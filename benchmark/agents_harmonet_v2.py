"""
HarmoNet v2 benchmark adapter.

This adapter keeps the original HarmoNet adapter intact and adds a conservative
OS-style scheduler around LLM calls:

- exact-cache hook for repeated production tasks, disabled by default for fair
  benchmark repeats;
- task profiling for patch, executable-code, and open-ended tasks;
- sparse activation: builder first, validator only when risk or validation
  uncertainty requires it;
- cheap validation before expensive LLM validation;
- optional fallback to the original HarmoNet adapter when v2 cannot validate a
  candidate.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from benchmark.tasks import BenchmarkTask
from harmonet.llm import get_llm_client
from harmonet.usage import METER


_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.I | re.S)
_DIFF_BLOCK_RE = re.compile(r"```(?:diff|patch)?\s*(diff --git.*?)```", re.I | re.S)


def _count_tokens(text: str) -> int:
    return max(1, int(len((text or "").split()) * 1.3))


def _keyword_hits(output: str, expected_keywords: List[str]) -> int:
    lowered = (output or "").lower()
    return sum(1 for keyword in expected_keywords if keyword.lower() in lowered)


def _missing_keywords(output: str, expected_keywords: List[str]) -> List[str]:
    lowered = (output or "").lower()
    return [keyword for keyword in expected_keywords if keyword.lower() not in lowered]


def _extract_code(output: str, expected_entry: str = "") -> str:
    output = output or ""
    blocks = _CODE_BLOCK_RE.findall(output)
    if blocks:
        preferred = [block for block in blocks if expected_entry and f"def {expected_entry}" in block]
        return max(preferred or blocks, key=len).strip()

    if expected_entry and f"def {expected_entry}" in output:
        return output[output.index(f"def {expected_entry}") :].strip()

    match = re.search(r"(^|\n)(from\s+\S+\s+import\s+|import\s+|def\s+|class\s+)", output)
    return output[match.start() :].strip() if match else output.strip()


def _extract_patch(output: str) -> str:
    output = output or ""
    blocks = _DIFF_BLOCK_RE.findall(output)
    if blocks:
        return max(blocks, key=len).strip()
    idx = output.find("diff --git")
    return output[idx:].strip() if idx >= 0 else ""


def _single_identifier_keyword(task: BenchmarkTask) -> str:
    if len(task.expected_keywords) != 1:
        return ""
    candidate = task.expected_keywords[0]
    return candidate if re.match(r"^[A-Za-z_]\w*$", candidate) else ""


@dataclass(frozen=True)
class TaskProfile:
    is_patch_task: bool
    is_executable_code_task: bool
    is_open_ended: bool
    risk: float
    expected_entry: str
    validator_required: bool
    repair_allowed: bool


@dataclass
class ValidationResult:
    ok: bool
    stage: str
    reasons: List[str]
    keyword_hits: int
    keyword_total: int
    extracted_chars: int


class _ExactCache:
    def __init__(self, max_items: int = 128):
        self.max_items = max_items
        self._items: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        value = self._items.get(key)
        if value is None:
            return None
        self._items.move_to_end(key)
        return dict(value)

    def put(self, key: str, value: Dict[str, Any]) -> None:
        self._items[key] = dict(value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)


_CACHE = _ExactCache(max_items=int(os.getenv("HARMONET_V2_CACHE_SIZE", "128")))


class HarmoNetV2Adapter:
    """Conservative v2 adapter with sparse scheduling and cheap validation."""

    def __init__(
        self,
        ticks: int = 2,
        validator_threshold: float = 0.65,
        keyword_threshold: float = 0.50,
        enable_cache: Optional[bool] = None,
        enable_v1_fallback: Optional[bool] = None,
    ):
        self.ticks = ticks
        self.validator_threshold = validator_threshold
        self.keyword_threshold = keyword_threshold
        self.enable_cache = (
            os.getenv("HARMONET_V2_CACHE", "0") == "1"
            if enable_cache is None
            else enable_cache
        )
        self.enable_v1_fallback = (
            os.getenv("HARMONET_V2_V1_FALLBACK", "0") == "1"
            if enable_v1_fallback is None
            else enable_v1_fallback
        )

    @property
    def name(self) -> str:
        return "harmonet_v2"

    def run(self, task: BenchmarkTask) -> Dict[str, Any]:
        started = time.perf_counter()
        METER.reset()
        cache_key = self._cache_key(task)
        if self.enable_cache:
            cached = _CACHE.get(cache_key)
            if cached is not None:
                cached["metadata"] = dict(cached.get("metadata", {}))
                cached["metadata"].update({"cache_hit": True, "elapsed_adapter_s": 0.0})
                cached["prompt_tokens"] = 0
                cached["completion_tokens"] = 0
                return cached

        profile = self._profile(task)
        prompt_tokens = 0
        completion_tokens = 0
        calls = 0
        stages: List[str] = []

        builder_prompt = self._builder_prompt(task, profile)
        builder_output, pt, ct = self._call_llm(builder_prompt, self._system_prompt(profile))
        prompt_tokens += pt
        completion_tokens += ct
        calls += 1
        stages.append("builder")

        validation = self._cheap_validate(builder_output, task, profile, stage="builder")
        final_output = builder_output
        accepted_stage = "builder"

        if not validation.ok and profile.repair_allowed:
            repair_prompt = self._repair_prompt(task, profile, builder_output, validation)
            repair_output, pt, ct = self._call_llm(repair_prompt, self._system_prompt(profile))
            prompt_tokens += pt
            completion_tokens += ct
            calls += 1
            stages.append("repair")
            repair_validation = self._cheap_validate(repair_output, task, profile, stage="repair")
            if repair_validation.ok or not validation.ok:
                final_output = repair_output
                validation = repair_validation
                accepted_stage = "repair"

        if profile.validator_required and not profile.is_patch_task:
            validator_prompt = self._validator_prompt(task, profile, final_output, validation)
            validator_output, pt, ct = self._call_llm(validator_prompt, self._system_prompt(profile))
            prompt_tokens += pt
            completion_tokens += ct
            calls += 1
            stages.append("validator")
            validator_validation = self._cheap_validate(validator_output, task, profile, stage="validator")
            if validator_validation.ok or not validation.ok:
                final_output = validator_output
                validation = validator_validation
                accepted_stage = "validator"

        if self.enable_v1_fallback and not validation.ok:
            from benchmark.agents_harmonet import HarmoNetAdapter

            fallback = HarmoNetAdapter(ticks=self.ticks).run(task)
            fallback_output = str(fallback.get("output", ""))
            fallback_validation = self._cheap_validate(fallback_output, task, profile, stage="v1_fallback")
            if fallback_validation.ok:
                final_output = fallback_output
                prompt_tokens += int(fallback.get("prompt_tokens", 0) or 0)
                completion_tokens += int(fallback.get("completion_tokens", 0) or 0)
                validation = fallback_validation
                accepted_stage = "v1_fallback"
                calls += int(fallback.get("metadata", {}).get("llm_calls", 2) or 2)
                stages.append("v1_fallback")

        result = {
            "output": final_output,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "token_source": "measured" if METER.snapshot()["measured"] else "estimated",
            "llm_calls": METER.snapshot()["calls"],
            "metadata": {
                "framework": "harmonet_v2",
                "calls": calls,
                "stages": stages,
                "accepted_stage": accepted_stage,
                "cache_hit": False,
                "profile": {
                    "is_patch_task": profile.is_patch_task,
                    "is_executable_code_task": profile.is_executable_code_task,
                    "is_open_ended": profile.is_open_ended,
                    "risk": round(profile.risk, 3),
                    "validator_required": profile.validator_required,
                    "repair_allowed": profile.repair_allowed,
                },
                "validation": {
                    "ok": validation.ok,
                    "stage": validation.stage,
                    "reasons": validation.reasons,
                    "keyword_hits": validation.keyword_hits,
                    "keyword_total": validation.keyword_total,
                    "extracted_chars": validation.extracted_chars,
                },
                "elapsed_adapter_s": round(time.perf_counter() - started, 4),
            },
        }
        if self.enable_cache and validation.ok:
            _CACHE.put(cache_key, result)
        return result

    def repair_after_eval(
        self,
        task: BenchmarkTask,
        failed_output: str,
        eval_error: str,
    ) -> Dict[str, Any]:
        """Run one test-aware repair pass after an external evaluator fails."""
        profile = self._profile(task)
        if not profile.is_executable_code_task:
            return {
                "output": failed_output,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "metadata": {"eval_repair_attempted": False, "reason": "not executable code"},
            }

        prompt = (
            "The previous Python solution failed the benchmark tests.\n"
            "Return only corrected executable Python code. Preserve the required function name.\n\n"
            f"Required function: {profile.expected_entry}\n\n"
            f"Task and public tests:\n{task.prompt}\n\n"
            f"Evaluator failure:\n{eval_error[:2000]}\n\n"
            f"Previous solution:\n{failed_output[:6000]}"
        )
        repaired, pt, ct = self._call_llm(prompt, self._system_prompt(profile))
        validation = self._cheap_validate(repaired, task, profile, stage="eval_repair")
        return {
            "output": repaired if validation.ok else failed_output,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "metadata": {
                "eval_repair_attempted": True,
                "eval_repair_static_ok": validation.ok,
                "eval_repair_reasons": validation.reasons,
            },
        }

    def _profile(self, task: BenchmarkTask) -> TaskProfile:
        prompt_lower = task.prompt.lower()
        category = (task.category or "").lower()
        is_patch = (
            category.startswith("swebench")
            or "unified diff" in prompt_lower
            or "diff --git" in prompt_lower
            or "swe-bench" in prompt_lower
        )
        expected_entry = _single_identifier_keyword(task)
        is_external_code = (
            category in {"humaneval", "mbpp"}
            or "humaneval" in prompt_lower
            or "mbpp" in prompt_lower
            or "return only python code" in prompt_lower
        )
        assume_code_checkable = os.getenv("HARMONET_V2_ASSUME_CODE_CHECKABLE", "0") == "1"
        is_executable_code = bool(expected_entry and (is_external_code or assume_code_checkable))
        is_open_ended = not is_patch and not is_executable_code

        risk = min(1.0, 0.25 + 0.18 * max(1, task.complexity))
        if is_patch:
            risk = max(risk, 0.90)
        if is_open_ended:
            risk = max(risk, 0.72)
        if len(task.prompt) > 6000:
            risk = min(1.0, risk + 0.12)

        validator_required = is_open_ended or (risk >= self.validator_threshold and not is_executable_code)
        repair_allowed = is_patch or is_executable_code
        return TaskProfile(
            is_patch_task=is_patch,
            is_executable_code_task=is_executable_code,
            is_open_ended=is_open_ended,
            risk=risk,
            expected_entry=expected_entry,
            validator_required=validator_required,
            repair_allowed=repair_allowed,
        )

    def _system_prompt(self, profile: TaskProfile) -> str:
        if profile.is_patch_task:
            return "Return valid unified diffs only. No markdown fences. No explanation."
        if profile.is_executable_code_task:
            return "Return executable Python code only. No prose unless code comments are required."
        return "Produce concise, correct technical work. Preserve all stated constraints."

    def _builder_prompt(self, task: BenchmarkTask, profile: TaskProfile) -> str:
        expected = ", ".join(task.expected_keywords)
        if profile.is_patch_task:
            return (
                "Generate the minimal valid unified diff for this task.\n"
                "Output must begin with diff --git when a patch is possible.\n\n"
                f"Required files or markers: {expected}\n\n"
                f"Task:\n{task.prompt}"
            )
        if profile.is_executable_code_task:
            return (
                f"Define `{profile.expected_entry}` and solve the task.\n"
                "Return only Python code.\n\n"
                f"Task:\n{task.prompt}"
            )
        return (
            "Solve the task with enough detail for review, but keep it concise.\n"
            f"Required terms: {expected}\n\n"
            f"Task:\n{task.prompt}"
        )

    def _repair_prompt(
        self,
        task: BenchmarkTask,
        profile: TaskProfile,
        output: str,
        validation: ValidationResult,
    ) -> str:
        missing = ", ".join(_missing_keywords(output, task.expected_keywords))
        if profile.is_patch_task:
            return (
                "The previous output failed static patch validation.\n"
                "Return only a corrected unified diff. No markdown fences.\n\n"
                f"Validation reasons: {'; '.join(validation.reasons)}\n"
                f"Missing markers: {missing}\n\n"
                f"Original task:\n{task.prompt}\n\n"
                f"Previous output:\n{output[:6000]}"
            )
        return (
            "The previous code failed static validation.\n"
            "Return only corrected Python code.\n\n"
            f"Validation reasons: {'; '.join(validation.reasons)}\n"
            f"Missing markers: {missing}\n\n"
            f"Original task:\n{task.prompt}\n\n"
            f"Previous output:\n{output[:6000]}"
        )

    def _validator_prompt(
        self,
        task: BenchmarkTask,
        profile: TaskProfile,
        candidate: str,
        validation: ValidationResult,
    ) -> str:
        return (
            "Review and finalize the candidate. If it is correct, return the final artifact unchanged. "
            "If it is incomplete, return only the corrected final artifact.\n\n"
            f"Task:\n{task.prompt}\n\n"
            f"Static validation: ok={validation.ok}; reasons={'; '.join(validation.reasons)}\n\n"
            f"Candidate:\n{candidate[:8000]}"
        )

    def _cheap_validate(
        self,
        output: str,
        task: BenchmarkTask,
        profile: TaskProfile,
        stage: str,
    ) -> ValidationResult:
        reasons: List[str] = []
        keyword_total = len(task.expected_keywords)
        keyword_hits = _keyword_hits(output, task.expected_keywords)
        extracted_chars = 0

        if not (output or "").strip():
            reasons.append("empty output")
            return ValidationResult(False, stage, reasons, keyword_hits, keyword_total, 0)

        if profile.is_patch_task:
            patch = _extract_patch(output)
            extracted_chars = len(patch)
            if not patch:
                reasons.append("no unified diff found")
            if patch and not patch.startswith("diff --git"):
                reasons.append("diff does not start with diff --git")
            if keyword_total and keyword_hits == 0:
                reasons.append("no expected patch markers found")
            return ValidationResult(not reasons, stage, reasons or ["patch static checks passed"], keyword_hits, keyword_total, extracted_chars)

        if profile.is_executable_code_task:
            code = _extract_code(output, profile.expected_entry)
            extracted_chars = len(code)
            if not code:
                reasons.append("no code found")
            try:
                tree = ast.parse(code or "")
            except SyntaxError as exc:
                reasons.append(f"syntax error: {exc.msg}")
                tree = None
            if profile.expected_entry and f"def {profile.expected_entry}" not in code:
                reasons.append(f"missing function {profile.expected_entry}")
            if tree is not None and profile.expected_entry:
                defs = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
                if profile.expected_entry not in defs:
                    reasons.append(f"function {profile.expected_entry} not defined")
            return ValidationResult(not reasons, stage, reasons or ["code static checks passed"], keyword_hits, keyword_total, extracted_chars)

        if keyword_total:
            hit_rate = keyword_hits / max(1, keyword_total)
            if hit_rate < self.keyword_threshold:
                reasons.append(f"keyword hit rate {hit_rate:.2f} < {self.keyword_threshold:.2f}")
        return ValidationResult(not reasons, stage, reasons or ["open-ended checks passed"], keyword_hits, keyword_total, len(output))

    def _call_llm(self, prompt: str, system_prompt: str) -> Tuple[str, int, int]:
        """실측 usage 기반. system_prompt를 포함한 API 실사용량을 델타로 반환한다."""
        before = METER.snapshot()
        output = get_llm_client().generate(prompt, system_prompt=system_prompt)
        after = METER.snapshot()
        return (output,
                after["prompt_tokens"] - before["prompt_tokens"],
                after["completion_tokens"] - before["completion_tokens"])

    def _cache_key(self, task: BenchmarkTask) -> str:
        payload = "\n".join(
            [
                task.id,
                task.category,
                task.prompt,
                ",".join(task.expected_keywords),
                str(task.complexity),
                os.getenv("RUNYOURAI_MODEL", ""),
                os.getenv("HARMONET_LLM_BACKEND", ""),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
