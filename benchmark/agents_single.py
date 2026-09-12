"""
benchmark/agents_single.py — 단일 호출 베이스라인 (Single-Call Baseline)

이 어댑터는 어떤 오케스트레이션도 하지 않는다. LLM을 정확히 한 번 호출하고 끝낸다.
멀티에이전트 구조도, 검증도, 수리도, 에스컬레이션도 없다.

존재 이유
---------
재측정 결과 HarmoNet의 토큰 우위는 대부분 "호출 횟수 1 vs 3"에서 나왔다.
따라서 다음 질문에 답할 수 없는 상태다:

    HarmoNet의 기제(공명 게이팅, 저비용 검증, 지연 에스컬레이션)가
    "그냥 한 번 호출하기"보다 나은가?

이 베이스라인이 그 질문의 대조군이다. 해석은 다음과 같다:

    HarmoNet ≈ single  →  기제가 기여하지 않음. 우위는 호출 횟수 감소가 전부
    HarmoNet > single  →  기제가 실제로 값을 함. 그 차이가 논문의 기여
    HarmoNet < single  →  기제가 해를 끼침

leave-one-out 어블레이션 관점에서는 "전부 제거" 행에 해당한다.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from benchmark.tasks import BenchmarkTask
from harmonet.llm import get_llm_client
from harmonet.trace import NO_COST, TaskState, meter_delta, model_used
from harmonet.usage import METER

_DEFAULT_SYSTEM = (
    "You are a precise Python engineer. Return a single fenced python code block. "
    "Implement exactly what is asked, matching the requested signature. "
    "Do not add explanations outside the code block."
)


class SingleCallAdapter:
    """LLM 1회 호출. 오케스트레이션 없음."""

    def __init__(self, system_prompt: str | None = None) -> None:
        self.system_prompt = system_prompt or os.getenv(
            "SINGLE_SYSTEM_PROMPT", _DEFAULT_SYSTEM
        )

    @property
    def name(self) -> str:
        return "single"

    def run(self, task: BenchmarkTask) -> Dict[str, Any]:
        METER.reset()
        started = time.perf_counter()
        state = TaskState(task.id, system=self.name)
        client = get_llm_client("builder")   # 역할별 모델 (WEEK1 A5)

        before = METER.snapshot("builder")
        output = client.generate(task.prompt, system_prompt=self.system_prompt)
        state.artifact = output or ""
        state.record("build", "builder", model_used("builder", client), meter_delta(before, METER.snapshot("builder")), (output or "")[:200])
        state.record("terminate", "single", "none", NO_COST, "single call, no verification")
        trace_path = state.save()

        snap = METER.snapshot()
        return {
            "trace_path": str(trace_path),
            "output": output or "",
            "prompt_tokens": snap["prompt_tokens"],
            "completion_tokens": snap["completion_tokens"],
            "token_source": "measured" if snap["measured"] else "estimated",
            "llm_calls": snap["calls"],
            "metadata": {
                "llm_calls": snap["calls"],
                "orchestration": "none",
                "elapsed_adapter_s": round(time.perf_counter() - started, 4),
            },
        }
