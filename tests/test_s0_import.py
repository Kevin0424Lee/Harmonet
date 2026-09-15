"""Week2-K3: s0 준비 — source(probe_reuse|new) 분기, 가져온 s0 의 원본 보존 대조, 실제 ID 파일 dry-run(전체는 HARMONET_K3_FULL=1)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import benchmark.s0_import as SI

ROOT = Path(__file__).resolve().parent.parent
IDS = json.loads((ROOT / "evidence" / "week2" / "pilot_explore_ids_bcb.json").read_text(encoding="utf-8"))
PROBE = {r["task_id"]: r for r in json.loads((ROOT / "evidence" / "week2" / "pool_probe_bcb_A.json").read_text(encoding="utf-8"))["rows"]}


def test_id_file_has_sources_59_reuse_41_new():
    assert IDS["n"] == 100 and sorted(IDS["sources"].values()).count("probe_reuse") == 59 and list(IDS["sources"].values()).count("new") == 41
    assert set(IDS["probe_reuse_ids"]) <= set(PROBE) and not set(IDS["new_s0_ids"]) & set(IDS["probe_reuse_ids"])


def test_prepare_requires_sources_and_never_generates_without_flag(tmp_path):
    with pytest.raises(RuntimeError, match="source"):
        SI.prepare({"ids": ["BigCodeBench/0"]}, PROBE, tmp_path, generate=False)


def test_import_one_and_check_preserves_original_then_tamper_is_caught(tmp_path):
    """probe_reuse 1건: 가져오기 → 원 후보·프롬프트·모델 ID·설정·토큰 출처·역사적 취득 비용 대조 통과; 후보를 바꾸면 예외 (docker 가시 검증 1회)."""
    tid = IDS["probe_reuse_ids"][0]
    out = SI.prepare({"ids": [tid], "sources": {tid: "probe_reuse"}}, PROBE, tmp_path, generate=False, log=lambda m: None)
    assert out == {"imported": [tid], "generated": [], "skipped_new": [], "failed": []}
    from benchmark.bcb import load_bcb
    task = load_bcb([tid])[0]
    d = tmp_path / tid.replace("/", "_") / "s0"
    checks = SI.check_imported(d, PROBE[tid], task)
    assert all(checks.values()) and json.loads((d / "prompt_context.json").read_text(encoding="utf-8"))["model_a"] == "claude-haiku-4-5-20251001"
    (d / "artifact.py").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="원본과 다르다"):
        SI.check_imported(d, PROBE[tid], task)
    nid = IDS["new_s0_ids"][0]
    out2 = SI.prepare({"ids": [nid], "sources": {nid: "new"}}, PROBE, tmp_path, generate=False, log=lambda m: None)
    assert out2["skipped_new"] == [nid] and out2["imported"] == []      # new 는 --generate 없이는 만들지 않는다


@pytest.mark.skipif(os.environ.get("HARMONET_K3_FULL") != "1", reason="전체 100 과제 s0 준비 dry-run (≈7분) — HARMONET_K3_FULL=1 로 실행; 결과는 evidence/week2/pilot_dryrun_s0.json")
def test_full_dryrun_imports_59_and_generates_41(tmp_path):
    out = tmp_path / "k3"
    p = subprocess.run([sys.executable, "-X", "utf8", "scripts/pilot_dryrun.py", "--backend", "mock-scenario", "--stage", "s0", "--out", str(out)],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-2000:]
    rep = json.loads(out.with_name("k3_s0.json").read_text(encoding="utf-8"))
    assert rep["n_imported"] == 59 and rep["n_generated"] == 41 and rep["failed"] == []


def test_recorded_full_dryrun_summary():
    rep = json.loads((ROOT / "evidence" / "week2" / "pilot_dryrun_s0.json").read_text(encoding="utf-8"))
    assert rep["n_imported"] == 59 and rep["n_generated"] == 41 and rep["failed"] == [] and sorted(rep["imported"]) == sorted(IDS["probe_reuse_ids"])


# ── Week2-M2/N3: 실제 신규 s0 경로(prepare → make_s0_guarded → budgeted_generate)의 실패 기록 보존 + 설정 식별자 ─────
# (M 보고에서 "406cea3 에 M2 회귀 테스트 포함" 이라 적었으나 실제로는 커밋되지 않았다 — N3 에서 영구 테스트로 추가. 이력은 docs/week1_notes.md 참조)
import benchmark.mock_scenario as MS
import benchmark.runloop as RL
from benchmark.mock_scenario import ScenarioMockClient, write_bcb_scenario
from harmonet.budget import Budget, BudgetStop

PILOT_SHA = "f" * 64                                   # 테스트용 파일럿 설정 식별자 (실제 APPROVAL/설정과 무관)


def _new_client(tmp_path, ids):
    sc = tmp_path / "sc.json"
    write_bcb_scenario(ids, {t: {"s0": "correct"} for t in ids}, sc, tokens={"prompt": 400, "completion": 500})
    c = ScenarioMockClient("claude-haiku-4-5", "claude-haiku-4-5", "claude-sonnet-4-6", str(sc)); c.role = "builder"
    return c


@pytest.mark.parametrize("script,reason,n_calls", [("timeout,timeout", "s0_unknown_cost_x2", 2), ("timeout,400", "call_failed", 2)])
def test_m2_n3_new_s0_failure_recorded_with_config_id_and_not_regenerated(tmp_path, monkeypatch, script, reason, n_calls):
    """source=new 내부 경로에 timeout×2(CallAborted) / timeout→400(BudgetStop) 주입: 실패 기록 1건, 예외 비용 == 기록 비용 == 원장 증가분,
    앞서 완료한 s0 파일·해시 보존, 설정 식별자(pilot_config_sha256) 가 null 아님·전달값과 일치, 재개 호출 0·원장·기록 불변. 유료 호출 0 (mock)."""
    monkeypatch.setattr(RL.time, "sleep", lambda s: None)
    monkeypatch.setenv("HARMONET_ALLOW_NO_REDIS", "1")
    ids = IDS["new_s0_ids"][:2]
    root = tmp_path / "run"; b = Budget(root / "budget.json", 5.0); c = _new_client(tmp_path, ids)
    doc = {"ids": ids, "sources": {t: "new" for t in ids}}
    monkeypatch.delenv("HARMONET_MOCK_FAIL_SCRIPT", raising=False); MS._FAIL_STATE["n"] = 0
    out0 = SI.prepare({"ids": ids[:1], "sources": {ids[0]: "new"}}, {}, root, generate=True, client_a=c, budget=b, log=lambda m: None, pilot_config_sha256=PILOT_SHA)
    d0 = root / ids[0].replace("/", "_") / "s0"
    assert out0["generated"] == [ids[0]] and (d0 / "sha256.txt").exists()
    h0 = (d0 / "sha256.txt").read_text(encoding="utf-8"); files0 = {p.name: p.read_bytes() for p in d0.iterdir()}
    spent0, calls0 = b.state()["spent"], b.state()["n_calls"]
    monkeypatch.setenv("HARMONET_MOCK_FAIL_SCRIPT", script); MS._FAIL_STATE["n"] = 0
    with pytest.raises(BudgetStop) as e:
        SI.prepare(doc, {}, root, generate=True, client_a=c, budget=b, log=lambda m: None, pilot_config_sha256=PILOT_SHA)
    st = b.state()
    d1 = root / ids[1].replace("/", "_") / "s0"
    recs = sorted(d1.glob("incomplete_*.json"))
    assert e.value.reason == reason and len(recs) == 1 and not (d1 / "sha256.txt").exists()
    rec = json.loads(recs[0].read_text(encoding="utf-8"))
    assert rec["task_id"] == ids[1] and rec["source"] == "new" and rec["stop_reason"] == reason and len(rec["attempts"]) == n_calls == len(e.value.attempts)
    assert rec["pilot_config_sha256"] == PILOT_SHA and rec["arm_config_hash"] is None                 # 파일럿 설정 식별자 ≠ arm 실행 설정 해시
    assert rec["s0_config"]["model_a"] == "claude-haiku-4-5" and rec["s0_config"]["system_prompt_sha256"]
    assert abs(st["spent"] - spent0 - rec["cost_usd"]) < 1e-12 and st["n_calls"] - calls0 == n_calls and e.value.usd == rec["cost_usd"]
    assert rec["measured_usd"] == 0.0 and abs(rec["unknown_reserved_usd"] - rec["cost_usd"]) < 1e-12
    assert (d0 / "sha256.txt").read_text(encoding="utf-8") == h0 and {p.name: p.read_bytes() for p in d0.iterdir()} == files0     # 완료 s0 보존
    monkeypatch.delenv("HARMONET_MOCK_FAIL_SCRIPT"); MS._FAIL_STATE["n"] = 0
    with pytest.raises(BudgetStop, match="자동 재생성 거부") as e2:
        SI.prepare(doc, {}, root, generate=True, client_a=c, budget=b, log=lambda m: None, pilot_config_sha256=PILOT_SHA)
    assert e2.value.reason == "unresolved_incomplete_s0" and b.state()["n_calls"] == st["n_calls"] and b.state()["spent"] == st["spent"]
    assert sorted(d1.glob("incomplete_*.json")) == recs and json.loads(recs[0].read_text(encoding="utf-8")) == rec and not (d1 / "sha256.txt").exists()   # 기록 내용 불변


def test_n3_missing_pilot_config_id_refuses_before_any_call(tmp_path, monkeypatch):
    monkeypatch.setenv("HARMONET_ALLOW_NO_REDIS", "1")
    ids = IDS["new_s0_ids"][:1]
    root = tmp_path / "run"; b = Budget(root / "budget.json", 5.0); c = _new_client(tmp_path, ids)
    doc = {"ids": ids, "sources": {ids[0]: "new"}}
    for bad in (None, ""):
        with pytest.raises(RuntimeError, match="pilot_config_sha256"):
            SI.prepare(doc, {}, root, generate=True, client_a=c, budget=b, log=lambda m: None, pilot_config_sha256=bad)
    assert b.state()["n_calls"] == 0 and sum(c.calls.values()) == 0 and not (root / ids[0].replace("/", "_")).exists()
    from benchmark.arms import make_s0_guarded
    with pytest.raises(RuntimeError, match="pilot_config_sha256"):
        make_s0_guarded(ids[0], "p", {"tests": []}, c, b, root, source="new")
    assert b.state()["n_calls"] == 0 and sum(c.calls.values()) == 0
