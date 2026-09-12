"""Week1-A4/A6: 어댑터 실행이 TaskState trace 를 남기고, validator 가 builder 산출물을 받았다는 증거가 trace 에 있는지."""
import hashlib
import json
import os
import contextlib
import io

import pytest

from benchmark.tasks import BenchmarkTask


@pytest.fixture
def trace_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HARMONET_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("HARMONET_TRACE_RUN_ID", "t")
    return tmp_path


def _task():
    return BenchmarkTask(id="x/1", category="humaneval", prompt="Write add(a, b).", expected_keywords=["add"],
                         complexity=1, spec={"kind": "code", "entry_point": "add", "tests": None})


def test_single_writes_trace(trace_env):
    from benchmark.agents_single import SingleCallAdapter
    r = SingleCallAdapter().run(_task())
    d = json.loads(open(r["trace_path"], encoding="utf-8").read())
    assert d["system"] == "single" and [a["kind"] for a in d["history"]] == ["build", "terminate"]
    assert d["history"][0]["cost"]["llm_calls"] == 1 and d["history"][0]["model"]
    assert d["cost_so_far"]["prompt_tokens"] == r["prompt_tokens"]


def test_harmonet_trace_has_verify_with_builder_artifact(trace_env):
    from benchmark.agents_harmonet import HarmoNetAdapter
    from harmonet.verify import extract_artifact
    with contextlib.redirect_stdout(io.StringIO()):
        r = HarmoNetAdapter(ticks=2).run(_task())
    d = json.loads(open(r["trace_path"], encoding="utf-8").read())
    kinds = [a["kind"] for a in d["history"]]
    assert "build" in kinds and "verify" in kinds, kinds
    build = next(a for a in d["history"] if a["kind"] == "build")
    verify = next(a for a in d["history"] if a["kind"] == "verify")
    assert build["cost"]["llm_calls"] >= 1
    assert verify["cost"]["llm_calls"] == 0 and verify["model"] == "none"
    assert "ast" in d["verification"]["method"]
    # validator 가 검증한 산출물 == builder 산출물 (sha 대조)
    sha = hashlib.sha256(extract_artifact(d["artifact"]).encode()).hexdigest()[:12]
    assert f"artifact_sha={sha}" in d["verification"]["evidence"], d["verification"]


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "traces")


@pytest.mark.parametrize("name", ["single", "harmonet", "harmonet_v2"])
def test_fixture_traces_match_schema(name):
    """Week1-A4c: 커밋된 스모크 trace 3개가 스키마를 통과하고 역할별 모델이 분리돼 있는지."""
    from harmonet.trace import validate_trace
    d = json.load(open(os.path.join(FIXTURES, f"{name}.json"), encoding="utf-8"))
    validate_trace(d)
    assert d["system"] == name and d["leak_risk"] is False
    if name == "harmonet_v2":
        models = {a["kind"]: a["model"] for a in d["history"]}
        assert models["build"] == "mock-a" and models["expert_review"] == "mock-b"
    if name == "harmonet":
        assert d["cost_attribution"] == "tick_aggregate"
