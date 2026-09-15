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


def test_unknown_failure_confirms_reservation_and_aborts_arm_after_two(tmp_path, monkeypatch):
    """(c) 응답 없는 예외 → 예약액 0.40 을 지출로 확정(unknown_cost), 1회면 재시도, 같은 과제에서 2회면 CallAborted (K2). $0 확정 경로 없음."""
    _fixed_cost(monkeypatch, 0.40)
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Client(raise_on_call=True)
    with pytest.raises(RL.CallAborted) as e:
        RL.budgeted_generate(c, b, "p", "s")
    st = b.state()
    assert c.calls == 2 and st["n_calls"] == 2 and st["unknown_cost_calls"] == 2 and abs(st["spent"] - 0.80) < 1e-9 and st["reserved"] == 0.0
    assert abs(e.value.usd - 0.80) < 1e-9 and all(a["unknown_cost"] for a in e.value.attempts) and st["stopped_reason"] is None


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
class _Http(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class _Flaky(_Client):
    """앞 n 회는 HTTP 429 응답(요금 없음 확실), 그 다음 성공."""

    def __init__(self, fail_first: int, status: int = 429):
        super().__init__()
        self.fail_first, self.status = fail_first, status

    def generate_once(self, prompt, system_prompt=None):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise _Http(self.status)
        return "ok"

    def generate(self, prompt, system_prompt=None):        # 클라이언트 자체 재시도 경로 — budgeted_generate 는 이걸 쓰면 안 된다
        raise AssertionError("budgeted_generate 가 generate_once 대신 generate 를 썼다")


def test_retry_reserves_and_commits_every_attempt(tmp_path, monkeypatch):
    """429 → 429 → 성공: 원장 3건 (실패 2건은 (b) actual 0·attempt_failed_unbilled, 성공 1건 실측 0.07), 예약 잔액 0, 중단 사유 없음."""
    _fixed_cost(monkeypatch, 0.10, actual=0.07)
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Flaky(2)
    out, cost, usd, wall = RL.budgeted_generate(c, b, "p", "s", note="t")
    st = b.state()
    assert c.calls == 3 and st["n_calls"] == 3 and st["stopped_reason"] is None and st["reserved"] == 0.0 and st["unbilled_failed_calls"] == 2
    assert abs(st["spent"] - 0.07) < 1e-9 and abs(usd - 0.07) < 1e-9 and cost["llm_calls"] == 3
    assert [e["actual"] for e in st["log"]] == [0.0, 0.0, 0.07] and all(e["attempt_failed_unbilled"] for e in st["log"][:2]) and not st["log"][2]["attempt_failed_unbilled"]
    assert [a["kind"] for a in cost["attempts"]] == ["unbilled_retry", "unbilled_retry", "success"] and not any(a["unknown_cost"] for a in cost["attempts"])


def test_retry_exhausted_on_429_stops_with_call_failed_and_zero_spend(tmp_path, monkeypatch):
    _fixed_cost(monkeypatch, 0.10)
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Flaky(99)
    with pytest.raises(BudgetStop) as e:
        RL.budgeted_generate(c, b, "p", "s")
    st = b.state()
    assert e.value.reason == "call_failed" and c.calls == RL.MAX_ATTEMPTS and st["n_calls"] == RL.MAX_ATTEMPTS and st["spent"] == 0.0


def test_http_400_is_unbilled_but_fatal(tmp_path, monkeypatch):
    _fixed_cost(monkeypatch, 0.10)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Flaky(99, status=400)
    with pytest.raises(BudgetStop) as e:
        RL.budgeted_generate(c, b, "p", "s")
    assert e.value.reason == "call_failed" and c.calls == 1 and b.state()["spent"] == 0.0 and b.state()["n_calls"] == 1


def test_unknown_then_success_charges_reserve_plus_measured(tmp_path, monkeypatch):
    """타임아웃 1회(c) → 성공: usd = 확정 예약 0.10 + 실측 0.07, 원장 spent 도 0.17 (arm 비용 == 원장)."""
    _fixed_cost(monkeypatch, 0.10, actual=0.07)
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)

    class _Timeout(_Client):
        def generate_once(self, prompt, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("read timed out")
            return "ok"
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Timeout()
    out, cost, usd, wall = RL.budgeted_generate(c, b, "p", "s")
    st = b.state()
    assert abs(usd - 0.17) < 1e-9 and abs(st["spent"] - 0.17) < 1e-9 and st["unknown_cost_calls"] == 1 and st["stopped_reason"] is None
    assert cost["n_unknown_attempts"] == 1 and cost["unknown_reserved_usd"] == 0.10


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


# ── Week2-K2: SDK 재시도 0 — 모의 HTTP 429→429→성공, HTTP 요청 수 == 원장 건수 ──
def test_sdk_http_429_twice_then_success_gives_three_ledger_entries(tmp_path, monkeypatch):
    import httpx2 as httpx
    from harmonet.llm import AnthropicClient
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    hits = {"messages": 0, "count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/count_tokens"):
            hits["count"] += 1
            return httpx.Response(200, json={"input_tokens": 300})
        hits["messages"] += 1
        if hits["messages"] <= 2:
            return httpx.Response(429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}})
        return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-4-5-20251001",
                                         "content": [{"type": "text", "text": "```python\nx = 1\n```"}], "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 300, "output_tokens": 20}})
    c = AnthropicClient(api_key="test-key", model="claude-haiku-4-5", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    c.role = "builder"
    assert c.client.max_retries == 0
    b = Budget(tmp_path / "budget.json", 1.0)
    out, cost, usd, wall = RL.budgeted_generate(c, b, "p", "s", note="k2")
    st = b.state()
    assert hits["messages"] == 3 == st["n_calls"] and hits["count"] == 1
    assert st["unbilled_failed_calls"] == 2 and [e["actual"] for e in st["log"]][:2] == [0.0, 0.0] and st["log"][2]["actual"] == usd
    assert abs(st["spent"] - usd) < 1e-12 and abs(usd - (330 * 0 + 300 * 1.0 + 20 * 5.0) / 1e6) < 1e-12   # haiku $1/$5 per M


# ── Week2-L1: 재시도까지 arm 별 예산 적용 ─────────────────────────────────
from benchmark.arms import MIN_MAX_TOKENS, _max_tokens_for   # noqa: E402
from harmonet.usage import METER                             # noqa: E402

HAIKU_IN, HAIKU_OUT = 1.0 / 1e6, 5.0 / 1e6            # prices: claude-haiku-4-5 $1 / $5 per M


class _ArmClient(_Client):
    """timeout 을 fail_first 회 낸 뒤 성공(300/100 토큰 실측)."""

    def __init__(self, fail_first=0):
        super().__init__(); self.fail_first = fail_first

    def generate_once(self, prompt, system_prompt=None):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise TimeoutError("read timed out")
        METER.record(300, 100, estimated=False, role=self.role, model=self.model)
        return "ok"


def _arm(remaining):
    return RL.ArmBudget(remaining, lambda r: _max_tokens_for("claude-haiku-4-5", r, 300), MIN_MAX_TOKENS, 4096)


def test_l1_timeout_then_arm_budget_exhausted_makes_no_further_call(tmp_path, monkeypatch):
    """코덱스 재현: arm 잔여 $0.00512, timeout → 잔여 0 → 다음 시도 max_tokens < 256 → 추가 호출 0, 귀속 $0.00512 (성공 없음, status refused_after_attempts)."""
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _ArmClient(fail_first=1)
    arm = _arm(0.00512)
    mt1 = min(int((0.00512 - 330 * HAIKU_IN) / HAIKU_OUT), 4096)                    # 958
    p1 = 330 * HAIKU_IN + mt1 * HAIKU_OUT                                             # ≈ 0.00512
    with pytest.raises(RL.CallAborted) as e:
        RL.budgeted_generate(c, b, "p", "s", arm=arm)
    st = b.state()
    assert e.value.reason == "arm_budget" and c.calls == 1 and st["n_calls"] == 1
    assert abs(e.value.usd - p1) < 1e-12 and abs(st["spent"] - p1) < 1e-12 and abs(arm.remaining_usd - (0.00512 - p1)) < 1e-12
    assert [a["max_tokens"] for a in e.value.attempts] == [mt1] and e.value.attempts[0]["unknown_cost"] and arm.max_tokens() < MIN_MAX_TOKENS
    # arms._call 경로: 출력 없음, usd 는 확정 예약액, 후속 호출 0
    import benchmark.arms as A
    c2 = _ArmClient(fail_first=1); b2 = Budget(tmp_path / "b2.json", 1.0)
    out, cost, usd, wall, mts, status = A._call(c2, b2, "p", "s", 0.00512, "t")
    assert status == "refused_after_attempts" and out is None and c2.calls == 1 and abs(usd - p1) < 1e-12 and cost["measured_usd"] == 0.0
    assert abs(cost["unknown_reserved_usd"] - p1) < 1e-12 and mts[0] == mt1 and mts[1] < MIN_MAX_TOKENS


def test_l1_timeout_with_enough_remaining_recomputes_max_tokens_and_matches_ledger(tmp_path, monkeypatch):
    """arm 잔여 $0.03: 시도1 max_tokens 4096(상한) 예약 P1 → timeout → 잔여 −P1 → 시도2 max_tokens 재계산(작아짐) → 성공 실측 M. usd = P1 + M == 원장 spent, 실측/귀속 분리."""
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _ArmClient(fail_first=1)
    arm = _arm(0.03)
    out, cost, usd, wall = RL.budgeted_generate(c, b, "p", "s", arm=arm)
    p1 = 330 * HAIKU_IN + 4096 * HAIKU_OUT
    mt2 = int((0.03 - p1 - 330 * HAIKU_IN) / HAIKU_OUT)
    m = 300 * HAIKU_IN + 100 * HAIKU_OUT
    st = b.state()
    assert [a["max_tokens"] for a in cost["attempts"]] == [4096, mt2] and mt2 < 4096
    assert abs(cost["unknown_reserved_usd"] - p1) < 1e-12 and abs(cost["measured_usd"] - m) < 1e-12 and abs(usd - (p1 + m)) < 1e-12
    assert abs(st["spent"] - usd) < 1e-12 and st["n_calls"] == 2 == c.calls and st["unknown_cost_calls"] == 1 and st["stopped_reason"] is None
    assert abs(arm.remaining_usd - (0.03 - p1 - m)) < 1e-12
