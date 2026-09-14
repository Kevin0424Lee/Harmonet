"""
harmonet/bcb_check.py — BigCodeBench 판정 함수 (Week2-D2 ③). **공식 이미지 안에서** import 된다 (bcb_harness.py, bcb_batch_harness.py 가 사용).
모듈 수준 부작용 없음. 판정 규칙·주장 범위는 bcb_harness.py docstring 참조.
"""
import builtins
import multiprocessing
import os
import sys
import time
import types
import unittest
from multiprocessing import Array, Manager, Value

from bigcodebench.eval.utils import TIMEOUT_LIMIT, create_tempdir, reliability_guard, safe_environment, swallow_io, time_limit

CHECKER_VERSION = "harmonet-bcb-check-d2.1"
LIMITS = {"max_as_limit": 30 * 1024, "max_data_limit": 30 * 1024, "max_stack_limit": 10, "min_time_limit": 1.0, "gt_time_limit": 1.0}
_SUCCESS, _FAILED, _TIMEOUT, _UNKNOWN = 0, 1, 2, 3
_MAP = {_SUCCESS: "pass", _FAILED: "fail", _TIMEOUT: "timeout", _UNKNOWN: None}


def _count_tests(test_code, out):  # 클린 프로세스: 후보 코드 없음
    _scrub()
    try:
        mod = types.ModuleType("__count__")
        with swallow_io():
            exec(compile(test_code, "__count__.py", "exec"), mod.__dict__)
            names = unittest.TestLoader().getTestCaseNames(getattr(mod, "TestCases"))
        out.value = len(names)
    except BaseException:  # noqa: BLE001
        out.value = -1


def _scrub():
    """fork 된 자식에서 부모 전역의 nonce·결과 경로·cfg 를 지운다 — 후보가 __main__ 을 뒤져도 결과 파일 이름을 알 수 없게."""
    import __main__
    for k in ("nonce", "out_path", "cfg", "res", "tests", "_write", "_dump", "_open"):
        __main__.__dict__.pop(k, None)


def _execute(code, test_code, timeout, lim, stat, counts, details):
    """자식 프로세스 본체. 판정 뒤 정리(create_tempdir/safe_environment 의 __exit__)에서 나는 예외는 삼키고 CLEANUP 에 기록만 한다 —
    그래야 exitcode 가 0 으로 남아 os._exit(n)·하드 크래시(정답 뒤 비정상 종료)만 exitcode 로 잡힌다. 공식도 정리 예외를 판정에 쓰지 않는다."""
    try:
        _execute_inner(code, test_code, timeout, lim, stat, counts, details)
    except BaseException as e:  # noqa: BLE001
        details["CLEANUP"] = (type(e).__name__ + ": " + str(e))[:300]


def _execute_inner(code, test_code, timeout, lim, stat, counts, details):
    _scrub()
    # 후보 exec 전에 바인딩 — 후보가 unittest 를 패치해도 아래 참조는 원본
    _TestCase, _TestSuite, _TestLoader, _TestResult = unittest.TestCase, unittest.TestSuite, unittest.TestLoader, unittest.TestResult
    _tc_run, _tc_call, _ts_run = _TestCase.run, _TestCase.__call__, _TestSuite.run
    _sys_modules_unittest = sys.modules.get("unittest")

    class _Result(_TestResult):
        def __init__(self):
            super().__init__()
            self.n_skipped = 0

        def addSkip(self, test, reason):
            self.n_skipped += 1
            super().addSkip(test, reason)

    with safe_environment(), create_tempdir():
        import os as _os
        import shutil as _shutil
        rmtree, rmdir, chdir = _shutil.rmtree, _os.rmdir, _os.chdir
        reliability_guard(lim["max_as_limit"], lim["max_data_limit"], lim["max_stack_limit"])
        module_name = "__test__"
        new_module = types.ModuleType(module_name)
        new_module.__dict__.update({"__builtins__": builtins, "__file__": f"{module_name}.py", "__package__": None, "__doc__": None,
                                    "sys": sys, "os": _os, "environ": _os.environ})
        try:
            with swallow_io():
                exec(compile(code + "\n" + test_code, f"{module_name}.py", "exec"), new_module.__dict__)
                sys.modules[module_name] = new_module
                sys.modules["unittest"] = _sys_modules_unittest          # 후보가 sys.modules['unittest'] 를 바꿨어도 되돌린다
                _TestCase.run, _TestCase.__call__, _TestSuite.run = _tc_run, _tc_call, _ts_run   # 후보가 패치했어도 원본으로
                TestCases = getattr(new_module, "TestCases")
                if not (isinstance(TestCases, type) and issubclass(TestCases, _TestCase)):
                    raise TypeError("TestCases is not a real unittest.TestCase subclass")
                suite = _TestLoader().loadTestsFromTestCase(TestCases)
                result = _Result()
                with time_limit(timeout):
                    _ts_run(suite, result)                              # 사전 바인딩된 TestSuite.run 으로 실행
            counts[0], counts[1], counts[2], counts[3] = result.testsRun, len(result.failures), len(result.errors), result.n_skipped
            for test, trace in result.failures + result.errors:
                details[test.id().split(".")[-1]] = trace[-400:]
            stat.value = _SUCCESS
        except BaseException as e:  # noqa: BLE001
            details["ALL"] = (type(e).__name__ + ": " + str(e))[:400]
            stat.value = _FAILED
        _shutil.rmtree, _os.rmdir, _os.chdir = rmtree, rmdir, chdir


def check(code, test_code, lim):
    """(stat, counts{testsRun,failures,errors,skipped}, expected, details). 공식 untrusted_check 와 같은 프로세스·타임아웃 구조."""
    exp = Value("i", -1)
    p0 = multiprocessing.Process(target=_count_tests, args=(test_code, exp))
    p0.start(); p0.join(timeout=60)
    if p0.is_alive():
        p0.kill(); p0.join()
    expected = int(exp.value)

    timeout = max(float(os.getenv("BIGCODEBENCH_TIMEOUT_PER_TASK", TIMEOUT_LIMIT)), lim["min_time_limit"], lim["gt_time_limit"]) + 1
    stat = Value("i", _UNKNOWN)
    counts = Array("i", [0, 0, 0, 0])
    manager = Manager()
    details = manager.dict()
    p = multiprocessing.Process(target=_execute, args=(code, test_code, timeout, lim, stat, counts, details))
    p.start()
    t_start = time.time()
    # join(timeout) 대신 is_alive() 폴링: 공식 가드(reliability_guard) 아래서 손자 프로세스가 sentinel 파이프를 물고 있으면 자식이 죽어도
    # join 이 타임아웃까지 기다린다 (D2 에서 확인, 250s). waitpid 기반 is_alive 는 즉시 본다.
    while time.time() - t_start < timeout + 1 and p.is_alive():
        time.sleep(0.05)
    if p.is_alive():
        p.terminate(); time.sleep(0.1)
    if p.is_alive():
        p.kill(); time.sleep(0.1)
    s = _MAP[stat.value] or "timeout"
    c = {"testsRun": counts[0], "failures": counts[1], "errors": counts[2], "skipped": counts[3], "exitcode": p.exitcode}
    d = dict(details)
    if s == "pass" and p.exitcode != 0:                 # 정답을 낸 뒤 os._exit(n)·비정상 종료 → 정상 종료가 아니다
        s, d = "fail", {**d, "EXIT": f"child exitcode {p.exitcode}"}
    if s == "pass":
        if expected < 0:
            s, d = "fail", {**d, "COUNT": "expected_tests unavailable (test module did not load cleanly)"}
        elif c["testsRun"] != expected or c["skipped"] != 0 or c["failures"] or c["errors"] or "ALL" in d:
            s = "fail"
            if c["testsRun"] != expected:
                d["COUNT"] = f"testsRun {c['testsRun']} != expected {expected}"
            if c["skipped"]:
                d["SKIPPED"] = str(c["skipped"])
    return s, c, expected, d


