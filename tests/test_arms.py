"""Week2-D5/F1: arm 실행기 — 예산 규칙(refused vs stop), 유효 코드 mock 종단간(MBPP+, docker 불필요), 멱등 재실행, s0 해시, 인프라 즉시 중단,
비용 귀속(B-solo = 자기 호출뿐), 분석기 입력 호환."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import benchmark.arms as A
from harmonet.budget import Budget, BudgetStop

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CORRECT = {"Mbpp/2": "def similar_elements(a, b):\n    return tuple(sorted(set(a) & set(b)))\n",
           "Mbpp/3": "def is_not_prime(n):\n    if n < 2:\n        return True\n    return any(n % d == 0 for d in range(2, int(n ** 0.5) + 1))\n"}
WRONG = {"Mbpp/2": "def similar_elements(a, b):\n    return ()\n", "Mbpp/3": "def is_not_prime(n):\n    return None\n"}
SCRIPT = {"s0": "wrong", "A-self": "correct", "A-role": "wrong", "B-expert": "correct", "B-solo": "correct"}
EXPECT = {"T": False, "A-self": True, "A-selfxk": True, "A-role": False, "B-expert": True, "B-solo": True}


def _scenario(tmp: Path, tokens=None) -> Path:
    from benchmark.mbppplus import load_mbppplus
    sc = {"tokens": tokens or {"prompt": 1000, "completion": 700},
          "tasks": {t.task_id: {"prompt": t.prompt, "variants": {"correct": CORRECT[t.task_id], "wrong": WRONG[t.task_id]}, "script": SCRIPT}
                    for t in load_mbppplus(list(CORRECT))}}
    p = tmp / "scenario.json"; p.write_text(json.dumps(sc), encoding="utf-8")
    return p


def _run(tmp: Path, run_id: str, k: int = 2, cap: str = "5", b_cont: str = "0.05", arms: str = None, extra_env: dict = None, expect_rc: int = 0) -> dict:
    ids = tmp / "ids.json"; ids.write_text(json.dumps({"ids": list(CORRECT)}), encoding="utf-8")
    env = dict(os.environ, HARMONET_LLM_BACKEND="mock-scenario", HARMONET_MOCK_SCENARIO=str(_scenario(tmp)),
               HARMONET_MODEL_BUILDER="claude-sonnet-4-6", HARMONET_MODEL_REVIEWER="claude-haiku-4-5", HARMONET_ALLOW_NO_REDIS="1",
               HARMONET_TRACE_RUN_ID=run_id, HARMONET_BUDGET_CAP=cap, HARMONET_BUDGET_ROOT=str(tmp / "budget"), HARMONET_ARMS_ROOT=str(tmp / "arms"),
               HARMONET_TRACE_DIR=str(tmp / "traces"), PYTHONIOENCODING="utf-8", **(extra_env or {}))
    out = tmp / f"{run_id}.json"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", "benchmark.arms", "--pool", "mbppplus", "--ids", str(ids), "--output", str(out),
                        "--b-cont", b_cont, "--a-call-median", "0.02", "--k", str(k)] + (["--arms", arms] if arms else []), cwd=str(ROOT), env=env,
                       capture_output=True, text=True)
    assert p.returncode == expect_rc, p.stdout[-1500:] + p.stderr[-1500:]
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("arms")
    return tmp, _run(tmp, "arms_f1")


def test_scenario_mock_end_to_end_hidden_matches_script(run):
    tmp, d = run
    rows = d["rows"]
    assert len(rows) == 2 * 6 * 2 and all(r["hidden_level"] == "functional" and r["hidden_exec_count"] >= 1 for r in rows)
    for r in rows:
        assert r["hidden_pass"] is EXPECT[r["arm"]], (r["arm"], r["rep"], r["outcome"])
    assert all(isinstance(r["hidden_pass"], bool) and "rep" in r and "infra" in r and "budget_refused" in r for r in rows)


def test_cost_attribution_b_solo_is_own_call_only(run):
    """B(haiku) 1000/700 토큰 = $0.0045. B-solo cost_usd == 0.0045, T == 0, s0(sonnet $0.0135) 는 shared_s0_cost 에만."""
    tmp, d = run
    bsolo = [r for r in d["rows"] if r["arm"] == "B-solo"]
    assert all(abs(r["cost_usd"] - 0.0045) < 1e-9 and r["models"] == ["claude-haiku-4-5"] for r in bsolo), bsolo[0]
    assert all(r["cost_usd"] == 0.0 for r in d["rows"] if r["arm"] == "T")
    assert all(abs(v - 0.0135) < 1e-9 for v in d["shared_s0_cost"].values())
    c = d["cost"]
    assert abs(c["total_spent_usd"] - (c["arms_own_usd"] + c["shared_s0_cost_total"])) < 1e-9 and c["n_unpriced"] == 0


def test_rerun_is_idempotent_and_s0_reused(run):
    tmp, d = run
    ledger_before = json.loads((tmp / "budget" / "arms_f1" / "budget.json").read_text(encoding="utf-8"))["n_calls"]
    d2 = _run(tmp, "arms_f1")
    ledger_after = json.loads((tmp / "budget" / "arms_f1" / "budget.json").read_text(encoding="utf-8"))["n_calls"]
    assert ledger_after == ledger_before, "재실행이 호출을 다시 했다"
    assert [r["trace_path"] for r in d2["rows"]] == [r["trace_path"] for r in d["rows"]]
    s0 = tmp / "arms" / "arms_f1" / "Mbpp_2" / "s0"
    (s0 / "artifact.py").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="해시 불일치"):
        _run(tmp, "arms_f1")


def test_rows_feed_gap_analysis(run):
    import gap_analysis as G
    r = G.analyze(run[1]["rows"], n_boot=50)
    assert r["n_tasks"] == 2 and r["k"] == 2 and "crossfit_gap" in r


def test_infra_at_s0_stops_before_any_further_call(tmp_path, monkeypatch):
    class C:
        model, role, max_tokens = "mock-a", "builder", 4096
        calls = 0

        def generate(self, prompt, system_prompt=None):
            C.calls += 1
            return "```python\nx = 1\n```"

    monkeypatch.setattr(A, "verify_visible", lambda art, spec: {"passed": False, "outcome": "aborted", "level": "functional", "n_run": 0, "n_passed": 0,
                                                                 "n_failed": 0, "flags": [], "applied": False, "evidence": "docker daemon down", "infra": True,
                                                                 "wall_ms": 1, "exec_count": 0, "sandbox": "docker"})
    clients = {"A": C(), "B": C()}
    from benchmark.runloop import InfraStop
    with pytest.raises(InfraStop):
        A.run_task_all_arms("t/1", "p", {"kind": "code", "tests": ["assert True"], "hidden_tests": ["assert True"]}, clients,
                            {"b_cont": 0.05, "a_call_median": 0.02, "k_max": 8}, None, tmp_path, "rid", 1, 2)
    assert C.calls == 1                                   # s0 호출 1회 뒤 후속 호출 0회


class _Client:
    model, role, max_tokens = "claude-haiku-4-5", "builder", 4096

    def __init__(self):
        self.calls = 0

    def count_input_tokens(self, prompt, system_prompt=None):
        return 300

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        return "```python\nx = 1\n```"


def test_max_tokens_rule_refuses_below_256_without_calling():
    c = _Client()
    out, cost, usd, wall, mt, status = A._call(c, None, "p" * 300, "s", remaining_usd=0.001, note="t")
    assert status == "refused" and out is None and c.calls == 0 and mt[-1] < A.MIN_MAX_TOKENS


def test_budget_stop_is_distinct_from_refused(tmp_path, monkeypatch):
    import benchmark.runloop as RL
    monkeypatch.setattr(RL, "projected_cost", lambda model, chars, max_tokens: 5.0)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Client()
    with pytest.raises(BudgetStop):
        A._call(c, b, "p" * 300, "s", remaining_usd=0.05, note="t")
    assert c.calls == 0 and b.state()["stopped_reason"] == "budget"


# ── Week2-J2 ──────────────────────────────────────────────────────────
def _ledger_calls(tmp: Path, run_id: str) -> int:
    return json.loads((tmp / "budget" / run_id / "budget.json").read_text(encoding="utf-8"))["n_calls"]


def test_result_reuse_keyed_by_config_hash_and_s0_hash_covers_all_files(tmp_path):
    """같은 설정 재실행 → 호출 0; 설정(b_cont)이 바뀌면 config_hash 불일치 → arm 재실행(호출 증가). s0 해시는 decision_signals.json 도 덮는다."""
    d1 = _run(tmp_path, "j2", k=1)
    n1 = _ledger_calls(tmp_path, "j2")
    assert all(r["config_hash"] == d1["rows"][0]["config_hash"] for r in d1["rows"])
    _run(tmp_path, "j2", k=1)
    assert _ledger_calls(tmp_path, "j2") == n1
    d3 = _run(tmp_path, "j2", k=1, b_cont="0.06")
    assert _ledger_calls(tmp_path, "j2") > n1 and d3["rows"][0]["config_hash"] != d1["rows"][0]["config_hash"]
    sig = tmp_path / "arms" / "j2" / "Mbpp_2" / "s0" / "decision_signals.json"
    sig.write_text(sig.read_text(encoding="utf-8").replace("{", "{\"tampered\": 1, ", 1), encoding="utf-8")
    with pytest.raises(AssertionError, match="해시 불일치"):
        _run(tmp_path, "j2", k=1, b_cont="0.06")


def test_max_tokens_rule_uses_counted_tokens_not_chars():
    """chars/3 폐기: 같은 잔여 예산에서 max_tokens 는 count_tokens 실측 × 1.10 으로만 정해진다."""
    from harmonet.pricing import price_for
    e, _ = price_for("claude-haiku-4-5")
    n_in = 1000
    mt = A._max_tokens_for("claude-haiku-4-5", 0.01, n_in)
    assert mt == int((0.01 - n_in * 1.10 * e["input"] / 1e6) / (e["output"] / 1e6))


# ── Week2-K2: 실패 2 + 성공 1 → arm 비용 == 원장 지출, 보고서 검산 통과 ───────
def test_failed_attempts_are_attributed_to_arm_and_ledger_matches(tmp_path, monkeypatch):
    """첫 호출(s0 build)이 429 → timeout(c) → 성공. arm/s0 비용에 (c) 확정 예약액이 들어가고, 원장 spent == Σ 셀 비용 + s0 비용 (spend_report 검산)."""
    import pilot_dryrun as PD
    monkeypatch.setenv("HARMONET_MOCK_FAIL_SCRIPT", "429,timeout")
    d = _run(tmp_path, "k2", k=1)
    led = json.loads((tmp_path / "budget" / "k2" / "budget.json").read_text(encoding="utf-8"))
    assert led["unbilled_failed_calls"] == 1 and led["unknown_cost_calls"] == 1 and led["stopped_reason"] is None
    assert led["n_calls"] == 2 + 2 + sum(r["n_attempts"] for r in d["rows"])       # s0 ×2 과제 (첫 s0 는 3 시도) + arm 시도 전부
    env = {"HARMONET_BUDGET_ROOT": str(tmp_path / "budget"), "HARMONET_BUDGET_ID": "k2"}
    rep = PD.spend_report(env, [d], 0.0)
    assert rep["total_spent_usd"] == led["spent"] and rep["check"].startswith("ledger ==")
    first_s0 = min(d["shared_s0_cost"].items())  # Mbpp/2 가 먼저 → 그 s0 에 (c) 예약액이 얹힘
    assert first_s0[1] > 0.0135                    # 정상 s0 $0.0135 + 확정 예약액


# ── Week2-L5: 미완료 arm 의 시도 기록 보존 (arms 경로) ───────────────────────
def test_l5_incomplete_arm_recorded_and_ledger_matches(tmp_path):
    """s0(sonnet, max_tokens 1024) 정상 → B-expert(haiku) timeout → 재시도 예약이 cap 초과 → BudgetStop(budget).
    완료 행 0, incomplete_arms 1 (attempts=[unknown], 비용 = 확정 예약액), 원장 == s0 + incomplete, 재실행 시 이중 계상 없음."""
    import pilot_dryrun as PD
    d = _run(tmp_path, "l5", k=1, cap="0.022", arms="B-expert", extra_env={"HARMONET_MOCK_FAIL_SCRIPT": "ok,timeout", "ANTHROPIC_MAX_TOKENS": "1024"}, expect_rc=2)
    led = json.loads((tmp_path / "budget" / "l5" / "budget.json").read_text(encoding="utf-8"))
    assert d["stopped_reason"] == "budget" and d["rows"] == [] and len(d["incomplete_arms"]) == 1
    inc = d["incomplete_arms"][0]
    assert inc["arm"] == "B-expert" and inc["incomplete"] is True and inc["stop_reason"] == "budget" and [a["kind"] for a in inc["attempts"]] == ["unknown"]
    assert inc["measured_usd"] == 0.0 and abs(inc["unknown_reserved_usd"] - inc["cost_usd"]) < 1e-12 and inc["n_attempts"] == 1
    s0 = d["cost"]["shared_s0_cost_total"]
    assert abs(led["spent"] - (s0 + d["cost"]["incomplete_usd"])) < 1e-9 and led["n_calls"] == 2 and led["unknown_cost_calls"] == 1
    assert abs(d["cost"]["total_spent_usd"] - led["spent"]) < 1e-9 and d["cost"]["measured_usd"] == 0.0
    env = {"HARMONET_BUDGET_ROOT": str(tmp_path / "budget"), "HARMONET_BUDGET_ID": "l5"}
    rep = PD.spend_report(env, [d], 0.0)
    assert rep["n_incomplete_arms"] == 1 and rep["arms_unknown_reserved_usd"] == inc["cost_usd"] and rep["check"].endswith("incomplete")
    assert not any((tmp_path / "arms" / "l5" / "Mbpp_2" / "B-expert" / "rep1").glob("result.json"))     # 미완료는 result.json 이 아니다
    # 재개(M1 fail-closed): 미해결 incomplete 가 있으므로 호출 전에 거부 — 에피소드는 그대로 1개, 원장 불변 (파일 단위 유일 → 이중 계상 없음)
    d2 = _run(tmp_path, "l5", k=1, cap="0.022", arms="B-expert", extra_env={"ANTHROPIC_MAX_TOKENS": "1024"}, expect_rc=2)
    led2 = json.loads((tmp_path / "budget" / "l5" / "budget.json").read_text(encoding="utf-8"))
    assert d2["stopped_reason"] == "unresolved_incomplete_arm" and len(d2["incomplete_arms"]) == 1
    assert abs(d2["cost"]["total_spent_usd"] - led2["spent"]) < 1e-9 and led2["spent"] == led["spent"] and led2["n_calls"] == led["n_calls"]


# ── Week2-M3: arm/s0 미완료 기록도 실측을 잃지 않는다 (cap_exceeded_post) ────────
def test_m3_cap_exceeded_post_incomplete_records_match_ledger(tmp_path):
    """max_tokens 256 이라 실측(완성 500 토큰) > 예약. cap 0.010: s0(sonnet) 실측 $0.0135 > cap → s0 미완료 기록 measured 0.0135 == 원장.
    cap 0.016: s0 뒤 B-expert 실측 $0.0045(1000/700 토큰) 로 초과 → arm 미완료 기록 measured 0.0045, 원장 == s0 + incomplete."""
    import pilot_dryrun as PD
    d = _run(tmp_path, "m3s0", k=1, cap="0.010", arms="B-expert", extra_env={"ANTHROPIC_MAX_TOKENS": "256"}, expect_rc=2)
    led = json.loads((tmp_path / "budget" / "m3s0" / "budget.json").read_text(encoding="utf-8"))
    inc = d["incomplete_arms"][0]
    assert d["stopped_reason"] == "cap_exceeded_post" and inc["arm"] == "s0" and abs(inc["measured_usd"] - 0.0135) < 1e-9 and inc["unknown_reserved_usd"] == 0.0
    assert abs(inc["cost_usd"] - led["spent"]) < 1e-9 and abs(d["cost"]["total_spent_usd"] - led["spent"]) < 1e-9 and d["rows"] == []
    d2 = _run(tmp_path, "m3arm", k=1, cap="0.016", arms="B-expert", extra_env={"ANTHROPIC_MAX_TOKENS": "256"}, expect_rc=2)
    led2 = json.loads((tmp_path / "budget" / "m3arm" / "budget.json").read_text(encoding="utf-8"))
    inc2 = d2["incomplete_arms"][0]
    assert inc2["arm"] == "B-expert" and inc2["stop_reason"] == "cap_exceeded_post" and abs(inc2["measured_usd"] - 0.0045) < 1e-9 and inc2["cost_usd"] == inc2["measured_usd"]
    assert abs(led2["spent"] - (d2["cost"]["shared_s0_cost_total"] + inc2["cost_usd"])) < 1e-9
    rep = PD.spend_report({"HARMONET_BUDGET_ROOT": str(tmp_path / "budget"), "HARMONET_BUDGET_ID": "m3arm"}, [d2], 0.0)
    assert abs(rep["arms_measured_usd"] - 0.0045) < 1e-9 and rep["arms_unknown_reserved_usd"] == 0.0 and rep["total_spent_usd"] == led2["spent"]


# ── Week2-M1: 중단 후 재개 시 arm 예산 초기화 차단 (fail-closed) ──────────────
def test_m1_resume_with_unresolved_incomplete_is_refused_before_any_call(tmp_path):
    """코덱스 재현: arm 상한 $0.010, 1차 timeout→400 귀속 $0.00622 (원장은 정지되지 않음, 추가 호출 가능 상태) → 패치 전 재개는 새 예산으로 성공 호출 $0.00450,
    누적 $0.01072 > 상한. 패치 후: 실제 CLI 경로 재개 → 호출 0, 원장 불변, 기존 incomplete 보존, stopped_reason unresolved_incomplete_arm."""
    d1 = _run(tmp_path, "m1", k=1, cap="5", b_cont="0.01", arms="B-expert", extra_env={"HARMONET_MOCK_FAIL_SCRIPT": "ok,timeout,400", "ANTHROPIC_MAX_TOKENS": "1024"}, expect_rc=2)
    led1 = json.loads((tmp_path / "budget" / "m1" / "budget.json").read_text(encoding="utf-8"))
    inc = d1["incomplete_arms"][0]
    assert d1["stopped_reason"] == "call_failed" and led1["stopped_reason"] is None and abs(inc["cost_usd"] - 0.00622) < 1e-9 and led1["n_calls"] == 3
    d2 = _run(tmp_path, "m1", k=1, cap="5", b_cont="0.01", arms="B-expert", extra_env={"ANTHROPIC_MAX_TOKENS": "1024"}, expect_rc=2)
    led2 = json.loads((tmp_path / "budget" / "m1" / "budget.json").read_text(encoding="utf-8"))
    assert d2["stopped_reason"] == "unresolved_incomplete_arm" and led2["n_calls"] == led1["n_calls"] and led2["spent"] == led1["spent"]
    assert [i["path"] for i in d2["incomplete_arms"]] == [inc["path"]] and d2["rows"] == []
    assert not (tmp_path / "arms" / "m1" / "Mbpp_2" / "B-expert" / "rep1" / "result.json").exists()
    assert (tmp_path / "arms" / "m1" / "Mbpp_2" / "s0" / "sha256.txt").exists()                          # 완료 s0 보존, 재생성 없음
