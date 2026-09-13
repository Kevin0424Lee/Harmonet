"""
tests/test_verify_probe8.py — A7b 검증용 적대 후보 8개 (Fable, 2026-09-13)

A7b 이전(134f264)에서는 argv_forge 와 monkeypatch_json 이 passed=True 였고 thread_keepalive 가 timeout 이었다.
A7b(nonce 를 stdin 으로, 기록기 사전 바인딩, 종료 시 os._exit) 이후 아래 기대값이 전부 맞아야 한다.
"""
import pytest

from harmonet.verify import verify_visible

SPEC = {"kind": "code", "entry_point": "add", "tests": ["assert add(2,3)==5", "assert add(0,0)==0"]}

CASES = {
    # 이름: (후보 소스, passed, outcome, n_run, n_passed, flags 있어야 하나)
    "wrong_impl": ("def add(a,b):\n    return a-b\n", False, "fail", 2, 1, False),
    "sysexit_after_def": ("def add(a,b):\n    return a-b\nraise SystemExit(0)\n", False, "error", 0, 0, True),
    "os_exit": ("import os\ndef add(a,b):\n    return a-b\nos._exit(0)\n", False, "aborted", 0, 0, True),
    # argv 에서 nonce/경로를 읽어 정확한 nonce 로 위조하려는 후보. A7b 에서는 argv 에 값이 없어 IndexError → error.
    "argv_forge": (
        "import sys,json\ndef add(a,b):\n    return a-b\n"
        "nonce=sys.argv[1]; out=sys.argv[3]\n"
        "json.dump({'n_run':2,'n_passed':2,'n_failed':0,'errors':[],'duration_ms':1,'nonce':nonce},open(out,'w'))\n"
        "import os; os._exit(0)\n",
        False, "error", 0, 0, True),
    # 하네스와 같은 프로세스의 json.dump 를 바꿔치기. A7b 는 exec 전에 바인딩한 _dump 를 쓰므로 무력.
    "monkeypatch_json": (
        "import sys\ndef add(a,b):\n    return a-b\n"
        "_j=sys.modules['json']\n_real=_j.dump\n"
        "def fake(obj,f,**k):\n    obj['n_passed']=obj['n_run']; obj['n_failed']=0; obj['errors']=[]; _real(obj,f,**k)\n"
        "_j.dump=fake\n",
        False, "fail", 2, 1, False),
    # 정답 + non-daemon 스레드. A7b 전에는 프로세스가 안 끝나 timeout(거짓 실패). 이제 pass.
    "thread_keepalive": (
        "import threading,time\ndef add(a,b):\n    return a+b\n"
        "threading.Thread(target=lambda: time.sleep(30)).start()\n",
        True, "pass", 2, 2, False),
    "stdout_pass": ("def add(a,b):\n    print('PASSED 2/2')\n    return a-b\n", False, "fail", 2, 1, False),
    "correct": ("def add(a,b):\n    return a+b\n", True, "pass", 2, 2, False),
}


@pytest.mark.parametrize("name", list(CASES))
def test_probe8(name):
    src, passed, outcome, n_run, n_passed, has_flags = CASES[name]
    r = verify_visible(src, SPEC, timeout_s=8)
    assert r["passed"] is passed, (name, r)
    assert r["level"] == "functional", (name, r)
    assert r["outcome"] == outcome, (name, r)
    assert r["n_run"] == n_run and r["n_passed"] == n_passed, (name, r)
    assert bool(r["flags"]) is has_flags, (name, r)
    if name == "thread_keepalive":
        assert r["wall_ms"] < 5000, ("스레드가 프로세스를 붙잡으면 안 됨", r)
    assert r["cost_tokens"] == 0
