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


def _docker_ok():
    if not shutil.which("docker"):
        return False
    try:
        import subprocess
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _docker_ok(), reason="skipped: docker unavailable (공식 이미지 안 채점 테스트)")
def test_bcb_official_check_in_image_pass_and_fail(task):
    """공식 이미지 안에서 D2 채점기: 정답은 pass, 틀린 답은 fail. docker 가 없으면 명시적 skip (사유 표시, 조용한 pass 금지 — D3)."""
    spec = task.spec(visible=True)
    good = V.score_hidden(task.prompt + "\n" + task._canonical, spec)
    assert good["passed"] is True and "official=0.2.4" in good["evidence"], good["evidence"]
    bad = V.score_hidden(task.prompt + "\n    return None\n", spec)
    assert bad["passed"] is False and bad["outcome"] == "fail", bad["evidence"]


def test_eligibility_cache_key_covers_filter_and_checker(monkeypatch):
    """D2 ⑤: 캐시 키 = 데이터 revision·이미지 digest·필터 버전·채점기 버전. 필터 버전만 바뀌어도 캐시는 무효."""
    import benchmark.bcb_eligibility as E
    h1 = E.config_hash()
    assert E.cache_valid({"config_hash": h1, "results": {}}, h1) and not E.cache_valid({"config_hash": "stale", "results": {}}, h1)
    monkeypatch.setattr(E, "FILTER_VERSION", "nondet-v999")
    h2 = E.config_hash()
    assert h2 != h1 and not E.cache_valid({"config_hash": h1, "results": {}}, h2)
    monkeypatch.setenv("HARMONET_BCB_IMAGE", "bigcodebench/bigcodebench-evaluate@sha256:0000")
    assert E.config_hash() != h2


def test_static_screen_v2_catches_file_calls():
    from benchmark.bcb import _NONDET_RE
    for src in (">>> task_func(open('a.txt'))", ">>> task_func(Path('x'))", ">>> os.path.exists('f')", ">>> shutil.copy(a, b)", ">>> input()"):
        assert _NONDET_RE.search(src), src
    assert not _NONDET_RE.search(">>> task_func([1, 2])\n[2, 4]")
