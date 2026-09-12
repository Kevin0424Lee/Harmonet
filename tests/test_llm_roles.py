"""Week1-A5: 역할별 모델 지정 (get_llm_client(role)) 점검 — mock 백엔드."""
import contextlib
import io
import json

import pytest

import harmonet.llm as L
from benchmark.tasks import BenchmarkTask


@pytest.fixture(autouse=True)
def fresh_llm(monkeypatch):
    """역할 클라이언트 캐시·경고 기록·기본 싱글턴을 테스트마다 초기화."""
    monkeypatch.setenv("HARMONET_LLM_BACKEND", "mock")
    for k in ("HARMONET_MODEL_DEFAULT", "HARMONET_MODEL_BUILDER", "HARMONET_MODEL_REVIEWER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(L, "_role_clients", {})
    monkeypatch.setattr(L, "_role_warned", set())
    monkeypatch.setattr(L, "_llm_client_singleton", None)
    yield


def _warnings(capsys):
    return [l for l in capsys.readouterr().out.splitlines() if "[LLM][WARN]" in l]


def test_unset_role_falls_back_to_default_with_one_warning(capsys):
    a = L.get_llm_client("builder")
    b = L.get_llm_client("builder")
    assert a is b and a.role == "builder" and a.model == "mock"
    warns = _warnings(capsys)
    assert len([w for w in warns if "'builder'" in w and "지정되지 않아" in w]) == 1, warns
    L.get_llm_client("builder")
    assert _warnings(capsys) == []          # 역할당 1회, 호출당 아님


def test_unknown_role_raises():
    with pytest.raises(ValueError):
        L.get_llm_client("architect")       # AgentRole 에는 있지만 LLM 역할(builder/reviewer)이 아님
    with pytest.raises(ValueError):
        L.get_llm_client("validator")


def test_same_model_for_builder_and_reviewer_warns(monkeypatch, capsys):
    monkeypatch.setenv("HARMONET_MODEL_DEFAULT", "mock-x")
    L.get_llm_client("builder")
    L.get_llm_client("reviewer")
    warns = _warnings(capsys)
    assert any("구별 불가" in w for w in warns), warns
    L.get_llm_client("reviewer")
    assert not any("구별 불가" in w for w in _warnings(capsys))   # 1회만


def test_distinct_models_are_separated_in_trace(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HARMONET_MODEL_BUILDER", "mock-a")
    monkeypatch.setenv("HARMONET_MODEL_REVIEWER", "mock-b")
    monkeypatch.setenv("HARMONET_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("HARMONET_TRACE_RUN_ID", "roles")
    from benchmark.agents_harmonet_v2 import HarmoNetV2Adapter
    task = BenchmarkTask(id="roles/api", category="api_design", prompt="Design an API with POST endpoints and schemas.",
                         expected_keywords=["POST", "schema"], complexity=2)   # open-ended → reviewer 단계가 돈다
    with contextlib.redirect_stdout(io.StringIO()):
        r = HarmoNetV2Adapter(ticks=2).run(task)
    d = json.loads(open(r["trace_path"], encoding="utf-8").read())
    by_kind = {a["kind"]: a for a in d["history"]}
    assert by_kind["build"]["model"] == "mock-a"
    assert by_kind["expert_review"]["model"] == "mock-b"
    assert by_kind["build"]["cost"]["llm_calls"] == 1 and by_kind["expert_review"]["cost"]["llm_calls"] == 1
    assert by_kind["verify"]["model"] == "none" and by_kind["verify"]["cost"]["llm_calls"] == 0
    assert not any("구별 불가" in w for w in _warnings(capsys))
