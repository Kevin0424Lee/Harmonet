"""
harmonet/bcb_harness.py — BigCodeBench 컨테이너 안 하네스 (Week2-C0 → D2 재작성). **공식 이미지 안에서만** 실행된다 (verify.py 가 docker 로 띄움).

주장 범위 (D2 ③): 공식 판정 흐름(exec(code + test) → TestCases 실행, 공식 create_tempdir / safe_environment / reliability_guard /
swallow_io / time_limit 그대로)에 **실행 수 검사 + unittest 참조 사전 바인딩**을 더한 것이다.
  - expected_tests: 후보 exec 전에 **별도 클린 프로세스**에서 test 모듈만 exec 하고 unittest.TestLoader 로 테스트 메서드 수를 센다.
  - 채점: 커스텀 TestResult 로 testsRun / failures / errors / skipped 수집.
    pass ⇔ testsRun == expected_tests ∧ skipped == 0 ∧ failures == errors == 0 ∧ 예외·타임아웃 없이 정상 종료(자식 exitcode 0).
    정답을 반환한 뒤 다른 스레드에서 나는 예외는 unittest 판정에 잡히지 않는다(공식도 동일) — os._exit(n≠0)·비정상 종료만 잡는다.
  - TestCase.run / TestCase.__call__ / TestSuite.run / TestLoader / TestResult 는 후보 exec **전에** 로컬에 바인딩하고, 후보 exec 뒤 클래스
    속성을 원본으로 되돌린 다음 실행한다 (A7b 의 _dump 방식).
  - **공식 채점기(bigcodebench.eval.unsafe_execute)는 실행 수를 검사하지 않는다** — TestCase.run 을 no-op 으로 바꾼 후보가 pass 로 나온다.
    그래서 판정 함수만 여기서 다시 쓰고 환경 헬퍼는 공식 것을 import 한다.
  - 범위 밖: TestResult 내부(addSuccess 등)를 깊이 패치하거나 결과 객체를 위조하는 고의적 후보. 그 수준의 적대는 subprocess 격리로 못 막는다.

프로토콜: stdin 한 줄 JSON {nonce, out_path, entry_point, tests:[test_module_src…], limits} → candidate.py → result_<nonce8>.json
{n_modules, n_run(=Σ testsRun), n_passed(모듈 단위), n_failed, expected, stats, errors, nonce}. 후보는 nonce·결과 경로를 볼 수 없다.
"""
import json
import multiprocessing
import os
import sys
import time

_dump, _open, _exit = json.dump, open, os._exit
cfg = json.loads(sys.stdin.readline())
nonce, out_path, entry, tests, lim = cfg["nonce"], cfg["out_path"], cfg["entry_point"], cfg["tests"], cfg["limits"]
t0 = time.time()
res = {"n_modules": 0, "n_run": 0, "n_passed": 0, "n_failed": 0, "expected": [], "counts": [], "stats": [], "errors": [],
       "duration_ms": 0, "nonce": nonce, "official": None, "checker": None}

def _write():
    res["duration_ms"] = int((time.time() - t0) * 1000)
    with _open(out_path, "w", encoding="utf-8") as f:
        _dump(res, f)


try:
    import bigcodebench
    sys.path.insert(0, os.getcwd())                        # python -I 는 스크립트 디렉터리를 sys.path 에 넣지 않는다
    from bcb_check import CHECKER_VERSION, check           # 같은 마운트 디렉터리의 harmonet/bcb_check.py 사본
    res["official"] = getattr(bigcodebench, "__version__", "installed")
    res["checker"] = CHECKER_VERSION
    with open("candidate.py", encoding="utf-8") as f:
        CODE = f.read()
except BaseException as e:  # noqa: BLE001
    res["errors"].append("setup: %s: %s" % (type(e).__name__, str(e)[:300]))
    _write(); _exit(0)


if __name__ == "__main__":
    multiprocessing.set_start_method("fork", force=True)
    for i, test_code in enumerate(tests):
        res["n_modules"] += 1
        try:
            stat, c, expected, d = check(CODE, test_code, lim)
            res["stats"].append(stat); res["counts"].append(c); res["expected"].append(expected); res["n_run"] += c["testsRun"]
            if stat == "pass":
                res["n_passed"] += 1
            else:
                res["n_failed"] += 1
                res["errors"].append("test_%d: %s: %s" % (i, stat, "; ".join("%s=%s" % (k, str(v)[:150]) for k, v in list(d.items())[:3])))
        except BaseException as e:  # noqa: BLE001
            res["n_failed"] += 1; res["stats"].append("error"); res["expected"].append(-1); res["counts"].append(None)
            res["errors"].append("test_%d: harness %s: %s" % (i, type(e).__name__, str(e)[:200]))
    _write()
    _exit(0)
