"""Week2-C0: BigCodeBench 로더·kind bcb 가드. 마지막 테스트는 공식 Docker 이미지가 필요하다 (없으면 skip 이 아니라 실패)."""
import ast
import shutil

import pytest

import harmonet.verify as V
from benchmark.bcb import _doctest_snippet, load_bcb


@pytest.fixture(scope="module")
def task():
    return load_bcb(["BigCodeBench/1"])[0]


def test_prompt_never_contains_test_or_canonical(task):
    assert task._test and task._canonical
    assert task._test not in task.prompt and task._canonical not in task.prompt
    spec = task.spec(visible=True)
    assert spec["hidden_tests"] == [task._test] and task._test not in "".join(spec["tests"]) and spec["hidden_exposed"] is False


def test_doctest_wrapper_is_a_testcases_module():
    src = _doctest_snippet(">>> f(2)\n4\n", "x")
    tree = ast.parse(src)
    assert any(isinstance(n, ast.ClassDef) and n.name == "TestCases" for n in tree.body)


def test_bcb_kind_without_docker_raises(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Docker"):
        V.verify_visible("def task_func():\n    return 1\n", {"kind": "bcb", "entry_point": "task_func", "tests": ["import unittest\nclass TestCases(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(task_func(), 1)\n"]})


def test_bcb_kind_static_gate_before_docker():
    r = V.verify_visible("def other():\n    pass\n", {"kind": "bcb", "entry_point": "task_func", "tests": ["x"]})
    assert r["level"] == "static" and "missing" in r["evidence"]


def test_bcb_official_check_in_image_pass_and_fail(task):
    """공식 이미지 안에서 공식 untrusted_check: 정답은 pass, 틀린 답은 fail. docker 가 없으면 이 테스트는 실패한다 (조용한 생략 금지)."""
    assert shutil.which("docker"), "docker 가 필요하다"
    spec = task.spec(visible=True)
    good = V.score_hidden(task.prompt + "\n" + task._canonical, spec)
    assert good["passed"] is True and "official=0.2.4" in good["evidence"], good["evidence"]
    bad = V.score_hidden(task.prompt + "\n    return None\n", spec)
    assert bad["passed"] is False and bad["outcome"] == "fail", bad["evidence"]
