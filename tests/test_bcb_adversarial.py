"""Week2-D2 ③: BCB 하네스 실행 수 검사·사전 바인딩 적대 테스트. 공식 Docker 이미지가 필요하다 — 없으면 명시적 skip (사유 표시).
주장 범위: 실행 수 검사 + unittest 참조 사전 바인딩. TestResult 내부를 깊이 패치하는 고의적 후보는 범위 밖."""
import shutil
import subprocess

import pytest

from benchmark.bcb import load_bcb
from harmonet.verify import score_hidden


def _docker_ok():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="skipped: docker unavailable (BCB 적대 테스트는 공식 이미지가 필요)")


@pytest.fixture(scope="module")
def task():
    return load_bcb(["BigCodeBench/0"])[0]      # 개발용 ID


def _hidden(task, code):
    return score_hidden(code, task.spec(visible=False))


def test_d_canonical_passes_and_tests_run_equals_expected(task):
    r = _hidden(task, task.prompt + "\n" + task._canonical)
    assert r["passed"] is True and r["n_modules"] == 1 and r["n_run"] > 0, r["evidence"]
    assert "n_run=%d" % r["n_run"] in r["evidence"]


def test_a_candidate_patches_testcase_run_to_noop(task):
    code = "import unittest\nunittest.TestCase.run = lambda self, result=None: None\nunittest.TestSuite.run = lambda self, result, debug=False: result\n" \
           + task.prompt + "\n    return 0\n"
    r = _hidden(task, code)
    assert r["passed"] is False, r["evidence"]


def test_b_candidate_injects_skip_into_test_class(task):
    code = ("import unittest\n"
            "def _isc(cls, **kw):\n"
            "    cls._classSetupFailed = False; cls._class_cleanups = []\n"   # 원본 __init_subclass__ 가 하던 일
            "    for n in dir(cls):\n"
            "        if n.startswith('test'):\n"
            "            setattr(cls, n, unittest.skip('injected')(getattr(cls, n)))\n"
            "unittest.TestCase.__init_subclass__ = classmethod(_isc)\n") + task.prompt + "\n    return 0\n"
    r = _hidden(task, code)
    assert r["passed"] is False and ("SKIPPED" in r["evidence"] or "COUNT" in r["evidence"]), r["evidence"]


def test_c_candidate_replaces_sys_modules_unittest(task):
    code = ("import sys, types\n"
            "fake = types.ModuleType('unittest')\n"
            "class TestCase:\n"
            "    def __init__(self, *a, **k): pass\n"
            "    def run(self, result=None): return result\n"
            "    def __call__(self, *a, **k): return None\n"
            "fake.TestCase = TestCase\n"
            "fake.mock = __import__('unittest.mock').mock\n"
            "sys.modules['unittest'] = fake\n") + task.prompt + "\n    return 0\n"
    r = _hidden(task, code)
    assert r["passed"] is False, r["evidence"]


def test_e_correct_output_then_abnormal_exit(task):
    """정답을 반환한 뒤 프로세스가 비정상 종료(백그라운드 스레드의 os._exit(3)) → fail. os._exit(0) 안에서 죽는 후보도 fail.
    atexit 은 multiprocessing 자식(os._exit 로 종료)에서 실행되지 않으므로 공격 경로가 아니다 — 테스트하지 않는다."""
    body = task._canonical
    thread = ("import threading, os, time\n" + task.prompt + "\n"
              "    threading.Thread(target=lambda: (time.sleep(0.3), os._exit(3))).start()\n" + body)
    r = _hidden(task, thread)
    assert r["passed"] is False, r["evidence"]
    r = _hidden(task, task.prompt + "\n    import os\n    os._exit(0)\n")
    assert r["passed"] is False, r["evidence"]
