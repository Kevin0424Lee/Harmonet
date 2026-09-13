"""
harmonet/bcb_harness.py — BigCodeBench 컨테이너 안 하네스 (Week2-C0). **공식 이미지 안에서만** 실행된다 (verify.py 가 docker -i 로 띄움).

판정은 전사하지 않고 공식 `bigcodebench.eval.untrusted_check` 를 그대로 호출한다 (v0.2.4 이미지에 설치된 패키지):
  exec(code + "\\n" + test_code) → unittest TestCases 실행 → 실패·오류 0 이면 pass, 예외면 fail, 시간 초과면 timeout.
  reliability_guard(rlimit)·safe_environment·time_limit(SIGALRM) 도 공식 그대로 (Linux 컨테이너라 전부 동작).
프로토콜은 우리 것: stdin 한 줄 JSON {nonce, out_path, entry_point, tests:[test_module_src…], limits} → 후보 파일 candidate.py 를 읽어
테스트 모듈마다 untrusted_check → result_<nonce>.json {n_run, n_passed, n_failed, errors, stats, nonce}. 후보는 nonce·결과 경로를 볼 수 없다.
가시 테스트(doctest → TestCases 래핑)와 히든 테스트(공식 test 모듈)가 같은 함수로 판정된다.
"""
import json
import os
import sys
import time

_dump, _open, _exit = json.dump, open, os._exit
cfg = json.loads(sys.stdin.readline())
nonce, out_path, entry, tests, lim = cfg["nonce"], cfg["out_path"], cfg["entry_point"], cfg["tests"], cfg["limits"]
t0 = time.time()
res = {"n_run": 0, "n_passed": 0, "n_failed": 0, "errors": [], "stats": [], "duration_ms": 0, "nonce": nonce, "official": None}


def _write():
    res["duration_ms"] = int((time.time() - t0) * 1000)
    with _open(out_path, "w", encoding="utf-8") as f:
        _dump(res, f)


try:
    import bigcodebench
    from bigcodebench.eval import untrusted_check
    res["official"] = getattr(bigcodebench, "__version__", "installed")
    with open("candidate.py", encoding="utf-8") as f:
        code = f.read()
except BaseException as e:  # noqa: BLE001
    res["errors"].append("setup: %s: %s" % (type(e).__name__, str(e)[:300]))
    _write(); _exit(0)

for i, test_code in enumerate(tests):
    res["n_run"] += 1
    try:
        stat, details = untrusted_check(code, test_code, entry, lim["max_as_limit"], lim["max_data_limit"], lim["max_stack_limit"],
                                        lim["min_time_limit"], lim["gt_time_limit"])
        res["stats"].append(stat)
        if stat == "pass":
            res["n_passed"] += 1
        else:
            res["n_failed"] += 1
            res["errors"].append("test_%d: %s: %s" % (i, stat, "; ".join("%s=%s" % (k, str(v)[:150]) for k, v in list(details.items())[:3])))
    except BaseException as e:  # noqa: BLE001
        res["n_failed"] += 1; res["stats"].append("error")
        res["errors"].append("test_%d: harness %s: %s" % (i, type(e).__name__, str(e)[:200]))
_write()
_exit(0)
