"""Week1-A8: 변조된 trace 는 validate_trace 를 통과하면 안 된다."""
import copy
import json
import os

import pytest

from harmonet.trace import validate_trace

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "traces")


def _load(name="harmonet_v2"):
    return json.load(open(os.path.join(FIXTURES, f"{name}.json"), encoding="utf-8"))


def test_fixture_is_valid_before_tampering():
    validate_trace(_load())


def test_inflated_cumulative_tokens_rejected():
    d = _load(); d["cost_so_far"]["prompt_tokens"] += 999999
    with pytest.raises(AssertionError):
        validate_trace(d)


def test_negative_llm_calls_rejected():
    d = _load(); d["history"][0]["cost"]["llm_calls"] = -7; d["cost_so_far"]["llm_calls"] = -7
    with pytest.raises(AssertionError):
        validate_trace(d)


def test_action_sum_mismatch_rejected():
    d = _load(); d["history"][0]["cost"]["completion_tokens"] += 1   # 행동만 바꾸고 누적은 그대로
    with pytest.raises(AssertionError):
        validate_trace(d)


def test_cost_usd_mismatch_rejected():
    d = _load(); d["cost_so_far"]["cost_usd"] = (d["cost_so_far"]["cost_usd"] or 0) + 0.5
    with pytest.raises(AssertionError):
        validate_trace(d)


def test_verify_action_with_tokens_rejected():
    d = _load(); v = next(a for a in d["history"] if a["kind"] == "verify")
    v["cost"]["llm_calls"] = 1; d["cost_so_far"]["llm_calls"] += 1
    with pytest.raises(AssertionError):
        validate_trace(d)


def test_tick_aggregate_skips_sum_check_but_not_sign_check():
    d = _load("harmonet")
    assert d["cost_attribution"] == "tick_aggregate"
    d2 = copy.deepcopy(d); d2["cost_so_far"]["prompt_tokens"] += 5   # 합계 검사는 생략됨
    validate_trace(d2)
    d3 = copy.deepcopy(d); d3["cost_so_far"]["wall_ms"] = -1          # 부호 검사는 유지
    with pytest.raises(AssertionError):
        validate_trace(d3)
