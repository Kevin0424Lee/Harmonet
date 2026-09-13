"""
harmonet/pricing.py — 날짜 박힌 가격표로 토큰 → USD (WEEK1 A8)

가격표: harmonet/prices_YYYY-MM.json (HARMONET_PRICE_SNAPSHOT 으로 파일 지정, 기본은 가장 최근 파일).
Action 마다 cost_usd 와 price_snapshot_id 를 기록해 어느 가격표로 계산했는지 남긴다.
모르는 모델은 조용히 0 으로 두지 않는다: cost_usd=None, flag "price_unknown", 경고 1회.
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_cache: Dict[str, Any] = {}
_warned: set = set()


def load_snapshot() -> Dict[str, Any]:
    path = os.getenv("HARMONET_PRICE_SNAPSHOT")
    if not path:
        files = sorted(glob.glob(str(_HERE / "prices_*.json")))
        if not files:
            raise RuntimeError("[pricing] harmonet/prices_*.json 이 없습니다")
        path = files[-1]
    if _cache.get("path") != path:
        with open(path, encoding="utf-8") as f:
            _cache.update(path=path, data=json.load(f))
    return _cache["data"]


def price_for(model: Optional[str]) -> Tuple[Optional[Dict[str, float]], str]:
    """(가격, snapshot_id). 모르는 모델이면 (None, snapshot_id)."""
    snap = load_snapshot()
    if not model or model == "none":
        return None, snap["snapshot_id"]
    entry = snap["models"].get(model)
    if entry is None:
        # API 응답의 model 은 날짜 붙은 id(claude-haiku-4-5-20251001) — 표의 별칭(claude-haiku-4-5)과 같은 가격 (Week2-B0 프로브에서 발견)
        entry = snap["models"].get(re.sub(r"-\d{8}$", "", model))
    if entry is None:
        for prefix, rule in snap.get("prefix_rules", {}).items():
            if model.startswith(prefix):
                entry = rule
                break
    return entry, snap["snapshot_id"]


def cost_usd(model: Optional[str], cost: Dict[str, Any]) -> Tuple[Optional[float], str, Optional[str]]:
    """토큰 비용 dict → (usd, snapshot_id, flag). LLM 호출이 없으면 0.0. 모르는 모델이면 (None, id, 'price_unknown')."""
    entry, sid = price_for(model)
    if int(cost.get("llm_calls", 0) or 0) == 0:
        return 0.0, sid, None
    if entry is None:
        key = f"unknown:{model}"
        if key not in _warned:
            _warned.add(key)
            print(f"[pricing][WARN] 모델 {model!r} 의 가격이 {sid} 에 없습니다 → cost_usd=None (flag price_unknown)")
        return None, sid, "price_unknown"
    # prompt_tokens 는 캐시 적중분을 포함한 처리량 → 캐시 토큰은 따로 빼서 각자 단가로
    pt = int(cost.get("prompt_tokens", 0) or 0)
    cr = int(cost.get("cache_read_tokens", 0) or 0)
    cw = int(cost.get("cache_write_tokens", 0) or 0)
    ct = int(cost.get("completion_tokens", 0) or 0)
    plain = max(0, pt - cr - cw)
    usd = (plain * entry["input"] + cr * entry["cache_read"] + cw * entry["cache_write"] + ct * entry["output"]) / 1e6
    return round(usd, 8), sid, None


if __name__ == "__main__":
    usd, sid, flag = cost_usd("claude-haiku-4-5", {"prompt_tokens": 1_000_000, "completion_tokens": 0, "llm_calls": 1})
    assert usd == 1.0 and flag is None, (usd, flag)
    assert cost_usd("claude-haiku-4-5-20251001", {"prompt_tokens": 1_000_000, "completion_tokens": 0, "llm_calls": 1})[0] == 1.0
    usd, sid, flag = cost_usd("claude-haiku-4-5", {"prompt_tokens": 2000, "cache_read_tokens": 1000, "completion_tokens": 0, "llm_calls": 1})
    assert abs(usd - (1000 * 1.0 + 1000 * 0.1) / 1e6) < 1e-12, usd
    assert cost_usd("mock-a", {"prompt_tokens": 5, "llm_calls": 1})[0] == 0.0
    assert cost_usd("unknown-model-x", {"prompt_tokens": 5, "llm_calls": 1})[2] == "price_unknown"
    assert cost_usd("none", {"llm_calls": 0})[0] == 0.0
    print("pricing.py self-check OK", sid)
