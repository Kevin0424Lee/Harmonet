"""
Week1-A1: builder 산출물이 validator에 도달해 기계 검증되는 경로의 점검.

- validator는 LLM을 호출하지 않는다 (호출 수 0)
- validator 판정의 method 에 "ast" 이상이 있고, evidence 의 artifact_sha 가 builder 산출물의 sha 와 같다
- architect 는 검증 요청 씨앗(target_role=validator)을 실행하지 않는다
"""
import hashlib
import os

import pytest

os.environ.setdefault("HARMONET_LLM_BACKEND", "mock")

from benchmark.agents_harmonet import HarmoNetAdapter
from harmonet.agent import AgentRole
from harmonet.verify import verify_visible, extract_artifact

BUILDER_CODE = "def add(a, b):\n    return a + b\n"


def test_verify_artifact_contract():
    r = verify_visible(BUILDER_CODE, {"kind": "code", "entry_point": "add", "tests": ["assert add(2, 3) == 5"]})
    assert r["passed"] is True and r["level"] == "functional" and r["outcome"] == "pass"
    assert r["method"] == ["ast", "test_exec"]
    assert r["cost_tokens"] == 0
    assert "artifact_sha=" in r["evidence"]


def test_builder_output_reaches_validator_without_llm():
    adapter = HarmoNetAdapter(ticks=3)
    universe, kuramoto, agents = adapter._build_pipeline()
    architect, builder, validator = agents

    llm_calls = {"builder": 0, "validator": 0, "architect": 0}

    def make_executor(role_name, output):
        def _exec(task_text):
            llm_calls[role_name] += 1
            return output
        return _exec

    spec = {"kind": "code", "entry_point": "add", "tests": ["assert add(2, 3) == 5"]}
    architect.create_and_deposit_seed("Write add(a, b) returning a + b.", metadata={"task_spec": spec})

    for _ in range(3):
        universe.propagate(dt=0.3)
        for a in agents:
            a.sync_phase(dt=0.1)
        # 각 역할의 'LLM'을 executor 로 대체. validator 는 executor 가 있어도 기계 검증 경로를 타야 한다.
        architect.scan_and_process(task_executor=make_executor("architect", "arch"))
        builder.scan_and_process(task_executor=make_executor("builder", f"```python\n{BUILDER_CODE}```"))
        validator.scan_and_process(task_executor=make_executor("validator", "SHOULD NOT BE CALLED"))
        kuramoto.step(dt=0.1)

    ver = [r.verification for r in validator.task_results if r.verification is not None]
    assert ver, "validator 가 검증 요청 씨앗을 실행하지 않았다"
    v = ver[-1]
    assert llm_calls["validator"] == 0, "validator 가 LLM(executor) 을 호출했다"
    assert llm_calls["architect"] == 0, "architect 가 검증 요청 씨앗을 집어갔다 (target_role 필터 실패)"
    assert llm_calls["builder"] >= 1
    assert "ast" in v["method"] and "test_exec" in v["method"], v
    assert v["passed"] is True, v
    assert v["cost_tokens"] == 0
    expected_sha = hashlib.sha256(extract_artifact(f"```python\n{BUILDER_CODE}```").encode()).hexdigest()[:12]
    assert f"artifact_sha={expected_sha}" in v["evidence"], v["evidence"]



if __name__ == "__main__":
    pytest.main([__file__, "-q"])
