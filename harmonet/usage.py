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
            # Anthropic 프롬프트 캐시. input_tokens 에는 빠져 있으므로 별도 집계하고 prompt_tokens 에 합산한다
            self.cache_read_input_tokens = 0
            self.cache_creation_input_tokens = 0

    def record(self, prompt_tokens: Optional[int], completion_tokens: Optional[int],
               estimated: bool = False, cache_read: int = 0, cache_creation: int = 0) -> None:
        with self._lock:
            # prompt_tokens = 모델이 처리한 입력 전체 (캐시 적중분 포함). 캐시 내역은 별도 필드로도 남긴다.
            self.prompt_tokens += int(prompt_tokens or 0) + int(cache_read or 0) + int(cache_creation or 0)
            self.completion_tokens += int(completion_tokens or 0)
            self.cache_read_input_tokens += int(cache_read or 0)
            self.cache_creation_input_tokens += int(cache_creation or 0)
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
        cache_read = cache_creation = 0
        if pt is None and ct is None:                       # Anthropic 형식
            pt = getattr(u, "input_tokens", None)
            ct = getattr(u, "output_tokens", None)
            cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
            cache_creation = getattr(u, "cache_creation_input_tokens", 0) or 0
        if pt is None and ct is None:
            self.record(None, None, estimated=True)
            return
        self.record(pt, ct, estimated=False, cache_read=cache_read, cache_creation=cache_creation)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
                "calls": self.calls,
                "estimated_calls": self.estimated_calls,
                "cache_read_input_tokens": self.cache_read_input_tokens,
                "cache_creation_input_tokens": self.cache_creation_input_tokens,
                "measured": self.estimated_calls == 0,
            }


METER = UsageMeter()
