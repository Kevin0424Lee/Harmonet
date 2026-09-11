"""
harmonet/usage.py — 실측 토큰 사용량 계측기

모든 LLM 백엔드가 API가 반환한 실제 usage를 이 계측기에 기록한다.
벤치마크 어댑터는 자체 추정 대신 이 값을 보고해야 한다.

사용법:
    from harmonet.usage import METER
    METER.reset()
    ... LLM 호출 ...
    snap = METER.snapshot()   # {'prompt_tokens':..., 'completion_tokens':..., 'calls':..., 'measured':...}

`measured=False`이면 해당 백엔드가 usage를 제공하지 않아 추정치가 섞였다는 뜻이다.
그 경우 결과 보고에 반드시 명시해야 한다.
"""
from __future__ import annotations
import threading
from typing import Dict, Optional


class UsageMeter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.calls = 0
            self.estimated_calls = 0   # usage 미제공으로 추정한 호출 수

    def record(self, prompt_tokens: Optional[int], completion_tokens: Optional[int],
               estimated: bool = False) -> None:
        with self._lock:
            self.prompt_tokens += int(prompt_tokens or 0)
            self.completion_tokens += int(completion_tokens or 0)
            self.calls += 1
            if estimated:
                self.estimated_calls += 1

    def record_from_response(self, response) -> None:
        """OpenAI 호환 / Anthropic 응답에서 usage를 추출해 기록."""
        u = getattr(response, "usage", None)
        if u is None:
            self.record(None, None, estimated=True)
            return
        pt = getattr(u, "prompt_tokens", None)
        ct = getattr(u, "completion_tokens", None)
        if pt is None and ct is None:                       # Anthropic 형식
            pt = getattr(u, "input_tokens", None)
            ct = getattr(u, "output_tokens", None)
        if pt is None and ct is None:
            self.record(None, None, estimated=True)
            return
        self.record(pt, ct, estimated=False)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
                "calls": self.calls,
                "estimated_calls": self.estimated_calls,
                "measured": self.estimated_calls == 0,
            }


METER = UsageMeter()
