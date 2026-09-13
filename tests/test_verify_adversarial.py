"""Week1-A7: 거짓 통과 방지. 전부 passed=False 여야 한다. 종료 코드·stdout 은 통과 신호가 아니다."""
import os

import pytest

from harmonet.verify import verify_visible, score_hidden

SPEC = {"kind": "code", "entry_point": "add", "tests": ["assert add(1, 2) == 3"]}


def _run(code, spec=SPEC, timeout=10.0):
    r = verify_visible(code, spec, timeout_s=timeout)
    assert r["passed"] is False, r
    return r


def test_system_exit_zero_at_module_level():
    r = _run("def add(a, b):\n    return 0\nimport sys\nsys.exit(0)\n")
    assert r["outcome"] == "error" and any(f.startswith("exit_call:module") for f in r["flags"]), r


def test_os_exit_zero_aborts_harness():
    r = _run("def add(a, b):\n    return 0\nimport os\nos._exit(0)\n")
    assert r["outcome"] == "aborted" and r["n_run"] == 0, r


def test_sys_exit_inside_if_main_is_flagged_and_caught():
    # 하네스는 __name__='candidate' 로 exec 하므로 블록은 안 돌지만, 플래그는 남고 테스트는 실제로 실행돼 실패한다
    r = _run("def add(a, b):\n    return 0\nif __name__ == '__main__':\n    import sys\n    sys.exit(0)\n")
    assert any("if_main" in f for f in r["flags"]) and r["outcome"] == "fail", r


def test_infinite_loop_times_out():
    r = _run("def add(a, b):\n    while True:\n        pass\n", timeout=3.0)
    assert r["outcome"] == "timeout", r


def test_empty_tests_is_no_tests_not_pass():
    r = _run("def add(a, b):\n    return a + b\n", {"kind": "code", "entry_point": "add", "tests": []})
    assert r["outcome"] == "no_tests" and r["level"] == "static", r


def test_printing_pass_to_stdout_is_not_a_pass():
    r = _run("def add(a, b):\n    print('pass'); print('1 passed'); return 0\n")
    assert r["outcome"] == "fail" and r["n_failed"] == 1, r


def test_candidate_prewriting_result_json_is_caught_by_nonce():
    # A7b: nonce 와 결과 경로는 stdin 으로 넘어가 후보 exec 전에 소비된다. 후보는 argv 에서 아무것도 못 얻는다.
    # 후보가 cwd 의 result_*.json 을 추측·위조하고 하네스를 죽인다 → 진짜 결과 파일 없음 → aborted
    code = (
        "def add(a, b):\n    return 0\n"
        "import os, json\n"
        "assert len(__import__('sys').argv) == 1  # A7b: argv 에 nonce/경로가 없어야 한다\n"
        "for name in ['result.json', 'result_00000000.json'] + [f for f in os.listdir('.') if f.startswith('result_')]:\n"
        "    json.dump({'n_run': 1, 'n_passed': 1, 'n_failed': 0, 'errors': [], 'duration_ms': 1, 'nonce': 'forged'}, open(name, 'w'))\n"
        "os._exit(0)\n"
    )
    r = _run(code)
    assert r["outcome"] == "aborted" and r["passed"] is False, r


def test_candidate_reading_argv_cannot_recover_nonce():
    # A7b 이전: sys.argv[1] 의 nonce 로 정확히 위조하면 passed=True 였다 (Fable 재현). 이제 argv 는 비어 있다.
    code = (
        "import sys, json\ndef add(a, b):\n    return 0\n"
        "nonce = sys.argv[1]; out = sys.argv[3]\n"
        "json.dump({'n_run': 1, 'n_passed': 1, 'n_failed': 0, 'errors': [], 'duration_ms': 1, 'nonce': nonce}, open(out, 'w'))\n"
        "import os; os._exit(0)\n"
    )
    r = _run(code)
    assert r["passed"] is False and r["outcome"] == "error" and r["n_run"] == 0, r


def test_candidate_monkeypatching_json_dump_is_ineffective():
    # A7b 이전: 하네스가 후보가 바꿔친 json.dump 로 결과를 써서 passed=True 였다 (Fable 재현). 이제 사전 바인딩된 _dump 를 쓴다.
    code = (
        "import sys\ndef add(a, b):\n    return 0\n"
        "_j = sys.modules['json']; _real = _j.dump\n"
        "def fake(obj, f, **k):\n    obj['n_passed'] = obj['n_run']; obj['n_failed'] = 0; obj['errors'] = []; _real(obj, f, **k)\n"
        "_j.dump = fake\n"
    )
    r = _run(code)
    assert r["passed"] is False and r["outcome"] == "fail" and r["n_passed"] == 0, r


def test_correct_candidate_with_lingering_thread_is_not_timeout():
    # A7b 이전: non-daemon 스레드가 프로세스를 붙잡아 정답이 timeout(거짓 실패). 이제 하네스가 os._exit 로 끝낸다.
    code = (
        "import threading, time\ndef add(a, b):\n    return a + b\n"
        "threading.Thread(target=lambda: time.sleep(30)).start()\n"
    )
    r = verify_visible(code, SPEC, timeout_s=8.0)          # _run 은 passed=False 를 단언하므로 직접 호출
    assert r["passed"] is True and r["outcome"] == "pass" and r["wall_ms"] < 5000, r


def test_apply_level_never_passes(tmp_path):
    # patch 종류는 apply 확인까지만: applied 는 True 일 수 있어도 passed 는 항상 False
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    patch = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-hello\n+bye\n"
    r = verify_visible(patch, {"kind": "patch", "repo_dir": str(repo), "base_commit": sha})
    assert r["applied"] is True and r["passed"] is False and r["level"] == "apply", r


def test_docker_sandbox_without_docker_raises(monkeypatch):
    monkeypatch.setenv("HARMONET_SANDBOX", "docker")
    monkeypatch.setattr("harmonet.verify.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError):
        verify_visible("def add(a, b):\n    return a + b\n", SPEC)


def test_no_api_keys_leak_into_candidate_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    code = ("import os\n"
            "def add(a, b):\n"
            "    assert 'ANTHROPIC_API_KEY' not in os.environ and 'OPENAI_API_KEY' not in os.environ, 'leak'\n"
            "    return a + b\n")
    r = verify_visible(code, SPEC)
    assert r["passed"] is True, r


def test_score_hidden_marks_post_hoc():
    r = score_hidden("def add(a, b):\n    return a + b\n", {"kind": "code", "hidden_tests": ["assert add(2, 2) == 4"]})
    assert r["passed"] is True and r["trigger"] == "post_hoc"
