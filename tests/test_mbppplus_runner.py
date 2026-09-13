"""Week2-B0: MBPP+ 러너 지표·로더 가드."""
import pytest

from benchmark.hidden_guard import HiddenExposedError
from benchmark.mbppplus import load_spec
from benchmark.mbppplus_g1 import summarize


def _row(base, plus, **kw):
    r = {"base_pass": base, "plus_only_pass": plus, "both_pass": base and plus, "passed": plus, "outcome": "pass" if plus else "fail",
         "cost_usd": 0.01, "token_source": "measured", "extraction": "fenced", "hidden_exposed": False}
    r.update(kw)
    return r


def test_summarize_three_metrics():
    s = summarize([_row(True, True), _row(True, False), _row(False, True), _row(False, False)])
    assert (s["base_pass"], s["plus_only_pass"], s["both_pass"]) == (0.5, 0.5, 0.25)
    assert s["outcomes"] == {"fail": 2, "pass": 2} and abs(s["cost_usd"] - 0.04) < 1e-9


def test_summarize_refuses_rows_without_explicit_hidden_flag():
    with pytest.raises(HiddenExposedError):
        summarize([_row(True, True, hidden_exposed=None)])


def test_spec_hash_mismatch_raises(tmp_path):
    p = tmp_path / "spec.json"
    p.write_text('{"tasks": {}}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="해시 불일치"):
        load_spec(p)


def test_spec_missing_raises(tmp_path):
    with pytest.raises(RuntimeError, match="스펙 없음"):
        load_spec(tmp_path / "nope.json")
