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
            # 역할별 분리 집계 (WEEK1 A5): role → 같은 키의 카운터. Action.cost 를 역할 단위로 귀속하기 위함
            self.by_role: Dict[str, Dict[str, int]] = {}
            self.last_model: Dict[str, Optional[str]] = {}   # role → 마지막 응답의 model (response.model 우선)
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.calls = 0
            self.estimated_calls = 0   # usage 미제공으로 추정한 호출 수
            # Anthropic 프롬프트 캐시. input_tokens 에는 빠져 있으므로 별도 집계하고 prompt_tokens 에 합산한다
            self.cache_read_input_tokens = 0
            self.cache_creation_input_tokens = 0

    def record(self, prompt_tokens: Optional[int], completion_tokens: Optional[int],
               estimated: bool = False, cache_read: int = 0, cache_creation: int = 0,
               role: str = "default", model: Optional[str] = None) -> None:
        with self._lock:
            pt = int(prompt_tokens or 0) + int(cache_read or 0) + int(cache_creation or 0)
            ct = int(completion_tokens or 0)
            # prompt_tokens = 모델이 처리한 입력 전체 (캐시 적중분 포함). 캐시 내역은 별도 필드로도 남긴다
            self.prompt_tokens += pt
            self.completion_tokens += ct
            self.cache_read_input_tokens += int(cache_read or 0)
            self.cache_creation_input_tokens += int(cache_creation or 0)
            self.calls += 1
            if estimated:
                self.estimated_calls += 1
            r = self.by_role.setdefault(role, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "estimated_calls": 0,
                                                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})
            r["prompt_tokens"] += pt
            r["completion_tokens"] += ct
            r["calls"] += 1
            r["estimated_calls"] += 1 if estimated else 0
            r["cache_read_input_tokens"] += int(cache_read or 0)
            r["cache_creation_input_tokens"] += int(cache_creation or 0)
            if model:
                self.last_model[role] = model

    def record_from_response(self, response, role: str = "default") -> None:
        """OpenAI 호환 / Anthropic 응답에서 usage를 추출해 기록. response.model 이 있으면 역할의 실제 모델로 기록."""
        model = getattr(response, "model", None)
        u = getattr(response, "usage", None)
        if u is None:
            self.record(None, None, estimated=True, role=role, model=model)
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
            self.record(None, None, estimated=True, role=role, model=model)
            return
        self.record(pt, ct, estimated=False, cache_read=cache_read, cache_creation=cache_creation, role=role, model=model)

    def snapshot(self, role: Optional[str] = None) -> Dict[str, int]:
        """role 을 주면 그 역할의 누적만 (같은 키 + last_model). 없으면 전체."""
        with self._lock:
            if role is not None:
                r = self.by_role.get(role) or {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "estimated_calls": 0,
                                               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
                return {**r, "total_tokens": r["prompt_tokens"] + r["completion_tokens"],
                        "measured": r["estimated_calls"] == 0, "last_model": self.last_model.get(role)}
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
