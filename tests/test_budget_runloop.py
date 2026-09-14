"""Week2-D1: 누적 예산 원장(①), 인프라 장애 중단(②), 컨테이너 정리(④)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import benchmark.runloop as RL
from harmonet.budget import Budget, BudgetStop


class _Client:
    model, max_tokens, role = "claude-haiku-4-5", 1000, "builder"

    def __init__(self, raise_on_call=False):
        self.calls = 0
        self.raise_on_call = raise_on_call

    def count_input_tokens(self, prompt, system_prompt=None):   # F2: count_tokens 실측 (여기서는 고정값)
        return 300

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        if self.raise_on_call:
            raise ConnectionError("simulated API failure")
        return "```python\ndef f():\n    return 1\n```"


class _NoCount(_Client):
    count_input_tokens = None


def _fixed_cost(monkeypatch, usd, actual=None):
    monkeypatch.setattr(RL, "projected_cost", lambda model, tokens, max_tokens: usd)
    monkeypatch.setattr(RL, "cost_usd", lambda model, cost: (usd if actual is None else actual, "snap", None))


# ── Week2-F2 ──────────────────────────────────────────────────────────

def test_projection_uses_counted_tokens_with_margin():
    """예약 = count_tokens 실측 × 1.10 × 입력단가 + max_tokens × 출력단가 (chars/3 폐기)."""
    from harmonet.budget import projected_cost
    assert abs(projected_cost("claude-haiku-4-5", 300, 1000) - (330 * 1.0 + 1000 * 5.0) / 1e6) < 1e-12


def test_client_without_count_tokens_is_not_called(tmp_path):
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _NoCount()
    with pytest.raises(RuntimeError, match="count_tokens"):
        RL.budgeted_generate(c, b, "p", "s")
    assert c.calls == 0 and b.state()["n_calls"] == 0


def test_commit_over_cap_stops_post(tmp_path, monkeypatch):
    """cap 1.00, 예약 0.40, 실측 커밋 1.10 → stopped_reason=cap_exceeded_post, BudgetStop(reason), 종료 코드 2."""
    _fixed_cost(monkeypatch, 0.40, actual=1.10)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Client()
    with pytest.raises(BudgetStop) as e:
        RL.budgeted_generate(c, b, "p", "s")
    assert e.value.reason == "cap_exceeded_post" and c.calls == 1
    st = b.state()
    assert st["spent"] == 1.10 and st["stopped_reason"] == "cap_exceeded_post" and st["reserved"] == 0.0
    saved = {}
    with pytest.raises(SystemExit) as ex:
        RL.run_loop(["t1", "t2"], lambda tid: RL.budgeted_generate(c, b, "p", "s"), lambda rows, stopped: saved.update(stopped=stopped), b)
    assert ex.value.code == 2 and saved["stopped"] in ("cap_exceeded_post", "budget")


def test_call_exception_commits_reserved_amount_and_stops(tmp_path, monkeypatch):
    """호출 예외 → $0 확정 금지: 예약액 0.40 을 지출로 확정, unknown_cost, 이후 호출 중단."""
    _fixed_cost(monkeypatch, 0.40)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Client(raise_on_call=True)
    with pytest.raises(BudgetStop) as e:
        RL.budgeted_generate(c, b, "p", "s")
    assert e.value.reason == "unknown_cost"
    st = b.state()
    assert st["spent"] == 0.40 and st["unknown_cost_calls"] == 1 and st["stopped_reason"] == "unknown_cost"
    assert not b.reserve(0.01)                          # 이후 예약 거부 = 호출 중단


def test_budget_stops_before_second_call_and_never_exceeds_cap(tmp_path, monkeypatch):
    """과제당 $0.60 × 3, cap $1 → 1번째 호출 뒤 2번째 호출 전에 중단. spent ≤ cap, stopped_reason='budget', 종료 코드 2."""
    _fixed_cost(monkeypatch, 0.60)
    b = Budget(tmp_path / "budget.json", 1.0)
    client = _Client()
    saved = {}

    def run_task(tid):
        out, cost, usd, wall = RL.budgeted_generate(client, b, "p" * 30, "s", note=tid)
        return {"task_id": tid, "cost_usd": usd, "line": ""}

    def write(rows, stopped):
        saved.update(rows=rows, stopped=stopped)

    with pytest.raises(SystemExit) as e:
        RL.run_loop(["t1", "t2", "t3"], run_task, write, b)
    assert e.value.code == 2
    assert client.calls == 1 and len(saved["rows"]) == 1 and saved["stopped"] == "budget"
    st = b.state()
    assert st["spent"] == 0.60 <= st["cap"] and st["reserved"] == 0.0 and st["stopped_reason"] == "budget" and st["n_calls"] == 1


def test_budget_refuse_happens_before_the_call(tmp_path, monkeypatch):
    _fixed_cost(monkeypatch, 1.5)
    b = Budget(tmp_path / "budget.json", 1.0)
    client = _Client()
    with pytest.raises(BudgetStop):
        RL.budgeted_generate(client, b, "p", "s")
    assert client.calls == 0 and b.state()["stopped_reason"] == "budget"


_CONCURRENT = r"""
import sys, json
from pathlib import Path
from harmonet.budget import Budget
b = Budget(Path(sys.argv[1]), 1.0)
done = 0
for i in range(3):
    if not b.reserve(0.40, sys.argv[2]):
        break
    b.commit(0.40, 0.40, sys.argv[2]); done += 1
print(done)
"""


def test_two_processes_share_ledger_and_stay_under_cap(tmp_path):
    """A·B 별도 프로세스가 같은 원장을 쓴다: 각 $0.40 × 3 시도, cap $1 → 합계 커밋 2회, spent 0.80 ≤ 1."""
    ledger = tmp_path / "budget.json"
    Budget(ledger, 1.0)
    procs = [subprocess.Popen([sys.executable, "-c", _CONCURRENT, str(ledger), arm], cwd=str(Path(__file__).resolve().parent.parent),
                              stdout=subprocess.PIPE, text=True) for arm in ("A", "B")]
    outs = [int(p.communicate(timeout=120)[0].strip()) for p in procs]
    st = json.loads(ledger.read_text(encoding="utf-8"))
    assert sum(outs) == st["n_calls"] == 2, (outs, st)
    assert abs(st["spent"] - 0.80) < 1e-9 and st["spent"] <= st["cap"] and st["stopped_reason"] == "budget"


def test_infra_failure_stops_after_first_task_but_candidate_abort_continues():
    calls = {"n": 0}

    def infra_task(tid):
        calls["n"] += 1
        return {"task_id": tid, "cost_usd": 0.0, "infra": True, "outcome": "aborted", "line": ""}

    saved = {}
    with pytest.raises(SystemExit) as e:
        RL.run_loop(["a", "b", "c"], infra_task, lambda rows, stopped: saved.update(rows=rows, stopped=stopped), None)
    assert e.value.code == 2 and calls["n"] == 1 and saved["stopped"] == "infra" and len(saved["rows"]) == 1

    calls["n"] = 0

    def candidate_abort(tid):
        calls["n"] += 1
        return {"task_id": tid, "cost_usd": 0.0, "infra": False, "outcome": "aborted", "line": ""}

    rows, stopped = RL.run_loop(["a", "b", "c"], candidate_abort, lambda rows, stopped: None, None)
    assert calls["n"] == 3 and len(rows) == 3 and stopped is None


def test_paid_backend_requires_ledger(monkeypatch):
    monkeypatch.setenv("HARMONET_LLM_BACKEND", "anthropic")
    with pytest.raises(RuntimeError, match="예산 원장"):
        RL.require_budget(None)
    monkeypatch.setenv("HARMONET_LLM_BACKEND", "mock")
    RL.require_budget(None)


def _docker_ok():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _docker_ok(), reason="skipped: docker unavailable (D1 ④ 컨테이너 정리 테스트는 실제 Docker 가 필요)")
def test_timeout_kills_and_removes_container(monkeypatch):
    monkeypatch.setenv("HARMONET_BCB_TIMEOUT_S", "3")
    monkeypatch.setenv("HARMONET_BCB_MARGIN_S", "15")
    from harmonet.verify import score_hidden
    T = "import unittest\nclass TestCases(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(task_func(), 1)\n"
    r = score_hidden("import time\ndef task_func():\n    while True: time.sleep(1)\n", {"kind": "bcb", "entry_point": "task_func", "hidden_tests": [T]})
    assert r["outcome"] == "timeout" and r["passed"] is False and r["infra"] is False
    ps = subprocess.run(["docker", "ps", "-a", "--filter", f"name={r['container']}", "--format", "{{.Names}}"], capture_output=True, text=True)
    assert ps.stdout.strip() == "", ps.stdout


# ── Week2-J2 ──────────────────────────────────────────────────────────
class _Flaky(_Client):
    """앞 n 회는 재시도 가능 오류(429), 그 다음 성공."""

    def __init__(self, fail_first: int):
        super().__init__()
        self.fail_first = fail_first

    def generate_once(self, prompt, system_prompt=None):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("429 rate_limit_error: slow down")
        return "ok"

    def generate(self, prompt, system_prompt=None):        # 클라이언트 자체 재시도 경로 — budgeted_generate 는 이걸 쓰면 안 된다
        raise AssertionError("budgeted_generate 가 generate_once 대신 generate 를 썼다")


def test_retry_reserves_and_commits_every_attempt(tmp_path, monkeypatch):
    """재시도 2회 후 성공 → 원장 3건(실패 시도 2건은 예약액 확정, 성공 1건 실측), 예약 잔액 0, 중단 사유 없음."""
    _fixed_cost(monkeypatch, 0.10, actual=0.07)
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Flaky(2)
    out, cost, usd, wall = RL.budgeted_generate(c, b, "p", "s", note="t")
    st = b.state()
    assert c.calls == 3 and st["n_calls"] == 3 and st["stopped_reason"] is None and st["reserved"] == 0.0
    assert abs(st["spent"] - (0.10 + 0.10 + 0.07)) < 1e-9
    assert [e["event"] for e in st["log"]] == ["commit"] * 3 and "attempt 1 failed" in st["log"][0]["note"]


def test_retry_exhausted_commits_unknown_cost(tmp_path, monkeypatch):
    _fixed_cost(monkeypatch, 0.10)
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Flaky(99)
    with pytest.raises(BudgetStop) as e:
        RL.budgeted_generate(c, b, "p", "s")
    st = b.state()
    assert e.value.reason == "unknown_cost" and c.calls == RL.MAX_ATTEMPTS and st["n_calls"] == RL.MAX_ATTEMPTS and abs(st["spent"] - 0.30) < 1e-9


def test_budget_stop_partial_rows_are_saved(tmp_path):
    """BudgetStop 에 partial 이 실려 오면 run_loop 가 부분 결과에 포함한다 (J2)."""
    b = Budget(tmp_path / "budget.json", 1.0)
    saved = {}

    def run_task(tid):
        if tid == "t2":
            raise BudgetStop("cap", "budget", partial={"task_id": "t2", "rows": [{"arm": "T"}], "cost_usd": 0.0, "line": "BUDGET STOP"})
        return {"task_id": tid, "cost_usd": 0.0, "line": ""}

    with pytest.raises(SystemExit) as e:
        RL.run_loop(["t1", "t2", "t3"], run_task, lambda rows, stopped: saved.update(rows=rows, stopped=stopped), b)
    assert e.value.code == 2 and saved["stopped"] == "budget" and [r["task_id"] for r in saved["rows"]] == ["t1", "t2"]
