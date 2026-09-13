"""Week2-A0: stdio 하네스 적대 테스트 (≥6). 후보 프로세스는 stdin 만 받고, 기대 출력·nonce·결과 경로를 볼 수 없다."""
import time

from harmonet.verify import verify_visible

SPEC = {"kind": "stdio", "per_test_timeout_s": 3.0,
        "tests": [{"input": "2 3\n", "output": "5\n"}, {"input": "10 -4\n", "output": "6\n"}]}
GOOD = "a,b=map(int,input().split())\nprint(a+b)\n"


def test_os_exit_zero_is_fail_not_pass():
    r = verify_visible("import os\nos._exit(0)\n", SPEC)
    assert r["passed"] is False and r["outcome"] == "fail" and r["n_passed"] == 0, r


def test_infinite_loop_times_out_and_child_tree_is_cleaned():
    t0 = time.perf_counter()
    r = verify_visible("import subprocess, sys, time\n"
                       "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"   # 손자 프로세스
                       "while True:\n    time.sleep(0.1)\n", SPEC)
    elapsed = time.perf_counter() - t0
    assert r["passed"] is False and r["outcome"] == "timeout", r
    assert elapsed < 2 * 3.0 * 2 + 15, f"자식 트리가 정리되지 않아 오래 걸림: {elapsed:.1f}s"


def test_empty_output_is_fail():
    r = verify_visible("input()\n", SPEC)
    assert r["passed"] is False and r["outcome"] == "fail", r


def test_exact_expected_output_passes():
    r = verify_visible(GOOD, SPEC)
    assert r["passed"] is True and r["outcome"] == "pass" and r["n_run"] == 2 == r["n_passed"], r


def test_correct_output_then_lingering_thread_passes_and_is_killed():
    code = GOOD + "import threading, time\nthreading.Thread(target=lambda: time.sleep(60)).start()\n"
    t0 = time.perf_counter()
    r = verify_visible(code, SPEC)
    assert r["passed"] is True and r["outcome"] == "pass", r
    assert "did not exit; killed" in r["evidence"], r["evidence"]
    assert time.perf_counter() - t0 < 3.0 * 2 + 10


def test_two_megabyte_output_fails():
    r = verify_visible("import sys\nsys.stdout.write('5' * 2_000_000)\n", SPEC)
    assert r["passed"] is False and "over cap" in r["evidence"], r["evidence"]


def test_candidate_cannot_find_nonce_in_argv_env_or_cwd():
    code = ("import os, sys\n"
            "leak = [a for a in sys.argv[1:]] + [k for k in os.environ if 'HARMONET' in k or 'KEY' in k]\n"
            "leak += [f for f in os.listdir('.') if f.startswith('result') or f.endswith('.json')]\n"
            "print('LEAK' if leak else 'clean')\n")
    r = verify_visible(code, {"kind": "stdio", "tests": [{"input": "x\n", "output": "clean\n"}]})
    assert r["passed"] is True, r["evidence"]      # 후보가 볼 수 있는 것이 없어야 'clean' 이 출력된다
