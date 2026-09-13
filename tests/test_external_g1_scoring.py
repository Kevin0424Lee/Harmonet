"""Week1-A7c: 러너(_run_one) 경로로 채점. 종료 코드 0 으로 빠져나가는 후보는 passed=False 여야 한다. 단위 테스트 숫자로 대체 불가."""
import os

import pytest

from benchmark.external_g1 import ExternalTask, _run_one, _task_spec, _visible_tests, evaluate_code_exitcode_legacy

HE_PREFIX = 'def add(a, b):\n    """Return a + b.\n    >>> add(2, 3)\n    5\n    >>> add(0, 0)\n    0\n    """\n'
HE_TESTS = "def check(candidate):\n    assert candidate(2, 3) == 5\n    assert candidate(-1, 1) == 0\n"


def _task():
    return ExternalTask(benchmark="humaneval", task_id="HumanEval/x", prompt="Complete:\n\n" + HE_PREFIX,
                        entry_point="add", tests=HE_TESTS, humaneval_prefix=HE_PREFIX)


class _Adapter:
    name = "adv"

    def __init__(self, output):
        self.output = output

    def run(self, task):
        return {"output": self.output, "prompt_tokens": 1, "completion_tokens": 1, "token_source": "measured", "llm_calls": 1, "metadata": {}}


def test_runner_rejects_exit_zero_candidate(monkeypatch):
    monkeypatch.setenv("BENCHMARK_VERBOSE_FRAMEWORK_LOGS", "1")   # stdout 리다이렉트 없이
    bad = "```python\ndef add(a, b):\n    return a - b\nraise SystemExit(0)\n```"
    m = _run_one(_Adapter(bad), _task(), repeat=1, timeout_s=20.0)
    assert m.passed is False, (m.outcome, m.eval_error)
    assert m.outcome == "error"                      # SystemExit 는 import 단계 error
    assert "def add" in m.candidate_code and m.extraction == "fenced"
    # 같은 후보를 구 채점기에 넣으면 통과했다 — 이것이 A7c 가 고치는 거짓 통과
    legacy_passed, _ = evaluate_code_exitcode_legacy(m.candidate_code, _task(), 20.0)
    assert legacy_passed is True


def test_runner_accepts_correct_candidate(monkeypatch):
    monkeypatch.setenv("BENCHMARK_VERBOSE_FRAMEWORK_LOGS", "1")
    m = _run_one(_Adapter("```python\ndef add(a, b):\n    return a + b\n```"), _task(), repeat=1, timeout_s=20.0)
    assert m.passed is True and m.outcome == "pass" and m.hidden_exposed is False


def test_visible_tests_come_from_doctest_and_hidden_from_check():
    spec = _task_spec(_task())
    assert len(spec["tests"]) == 2 and all("assert repr(_r) ==" in t for t in spec["tests"])
    assert len(spec["hidden_tests"]) == 1 and "check(add)" in spec["hidden_tests"][0]
    assert spec["hidden_exposed"] is False


def test_mbpp_hidden_is_exposed():
    t = ExternalTask(benchmark="mbpp", task_id="mbpp_1", prompt="p", entry_point="f", tests="assert f(1) == 1\nassert f(2) == 2")
    spec = _task_spec(t)
    assert spec["hidden_exposed"] is True and spec["tests"] == spec["hidden_tests"] == ["assert f(1) == 1", "assert f(2) == 2"]
