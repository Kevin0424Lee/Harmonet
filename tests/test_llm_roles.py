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


# ── Week2-B2: 비용 사전 점검 / 합계 ─────────────────────────────────

class _FakeModels:
    def __init__(self, reported_id):
        self.reported_id = reported_id

    def retrieve(self, model):
        return type("Info", (), {"id": self.reported_id})()


class _FakeSDK:
    def __init__(self, reported_id):
        self.models = _FakeModels(reported_id)
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        raise AssertionError("사전 점검 실패 뒤에는 호출이 없어야 한다")


def _anthropic_with(reported_id):
    c = L.AnthropicClient.__new__(L.AnthropicClient)      # 생성자 우회 (API 키·SDK 불필요)
    c.model, c.client, c.role = "claude-haiku-4-5", _FakeSDK(reported_id), "builder"
    return c


def test_preflight_unpriced_model_raises_before_any_call():
    c = _anthropic_with("claude-unpriced-9-20991231")
    with pytest.raises(RuntimeError, match="가격이"):
        L._assert_model_available(c, "builder")
    assert c.client.calls == 0


def test_preflight_dated_id_normalizes_to_priced_alias():
    c = _anthropic_with("claude-haiku-4-5-20251001")
    L._assert_model_available(c, "builder")                  # 예외 없음
    assert c.client.calls == 0


def test_sum_cost_with_one_unpriced_row_is_none():
    from harmonet.pricing import sum_cost
    assert sum_cost([{"cost_usd": 0.01}, {"cost_usd": None}, {"cost_usd": 0.02}]) == {"cost_usd": None, "n_unpriced": 1}
    assert sum_cost([{"cost_usd": 0.01}, {"cost_usd": 0.02}]) == {"cost_usd": 0.03, "n_unpriced": 0}
