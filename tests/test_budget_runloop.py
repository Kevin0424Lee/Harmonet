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

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        return "```python\ndef f():\n    return 1\n```"


def _fixed_cost(monkeypatch, usd):
    monkeypatch.setattr(RL, "projected_cost", lambda model, chars, max_tokens: usd)
    monkeypatch.setattr(RL, "cost_usd", lambda model, cost: (usd, "snap", None))


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
