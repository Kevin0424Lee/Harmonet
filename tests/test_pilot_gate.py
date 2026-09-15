"""Week2-J5: 실행 게이트 — 조건 하나라도 없으면 Gate(RuntimeError), 호출 0회. PREREG 설정 절 = 설정 파일(단일 출처)."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pilot_dryrun as PD      # noqa: E402
import prereg_render as PR     # noqa: E402

CFG = json.loads(PR.CONFIG.read_text(encoding="utf-8"))
IDS_OK = {"ids": ["BigCodeBench/0"], "probe_reuse_ids": [], "flip_subset_n": 1, "flip_subset_ids": ["BigCodeBench/0"]}


def _args(backend="anthropic"):
    return SimpleNamespace(backend=backend)


def test_prereg_config_block_is_current():
    assert subprocess.run([sys.executable, "-X", "utf8", "scripts/prereg_render.py", "--check"], cwd=str(ROOT), capture_output=True).returncode == 0


def test_gate_config_hash_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(PD, "config_sha256", lambda p: "deadbeef" * 8)
    with pytest.raises(PD.Gate, match="설정 해시"):
        PD.gate_common(_args(), CFG, IDS_OK, tmp_path, "explore")


def test_gate_flip_subset_missing(tmp_path):
    with pytest.raises(PD.Gate, match="뒤집힘"):
        PD.gate_common(_args(), CFG, {"ids": ["BigCodeBench/0"], "probe_reuse_ids": []}, tmp_path, "explore")


def test_gate_s0_import_incomplete(tmp_path):
    ids = {**IDS_OK, "probe_reuse_ids": ["BigCodeBench/0", "BigCodeBench/1"]}
    with pytest.raises(PD.Gate, match="s0 가져오기 미완료 2/2"):
        PD.gate_common(_args(), CFG, ids, tmp_path, "explore")


def test_gate_docker_preflight_failure_blocks(monkeypatch, tmp_path):
    import benchmark.bcb as B
    monkeypatch.setattr(B, "bcb_preflight", lambda: (_ for _ in ()).throw(RuntimeError("docker daemon down")))
    with pytest.raises(RuntimeError, match="docker daemon down"):
        PD.gate_common(_args("mock-scenario"), CFG, IDS_OK, tmp_path, "explore")
    with pytest.raises(PD.ApprovalError):                    # 실제 백엔드는 docker 이전에 승인 대조에서 막힌다 (K1)
        PD.gate_common(_args(), CFG, IDS_OK, tmp_path, "explore")


def test_gate_round0_missing_or_incomplete(tmp_path):
    with pytest.raises(PD.Gate, match="0회차"):
        PD.gate_round0(tmp_path / "round0_bcont.json")
    (tmp_path / "round0_bcont.json").write_text(json.dumps({"b_cont": 0.0, "a_call_median": 0.003}), encoding="utf-8")
    with pytest.raises(PD.Gate, match="불완전"):
        PD.gate_round0(tmp_path / "round0_bcont.json")


def test_gate_frozen_policy_required_for_confirm(monkeypatch, tmp_path):
    import benchmark.bcb as B
    monkeypatch.setattr(B, "bcb_preflight", lambda: {"ok": True})
    with pytest.raises(PD.Gate, match="동결 정책"):
        PD.gate_common(_args("mock-scenario"), CFG, IDS_OK, tmp_path, "confirm")


def test_backend_and_stage_have_no_default():
    p = subprocess.run([sys.executable, "-X", "utf8", "scripts/pilot_dryrun.py", "--out", "x"], cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode == 2 and "--backend" in p.stderr and "--stage" in p.stderr


# ── Week2-K1/L2: 승인 기록 대조 — 값 단위 + 동결 파일 내부 + freeze_commit blob + 검증 범위 파일 해시 ─────
import hashlib   # noqa: E402
import approval as AP   # noqa: E402
from benchmark.features import FEATURES_VERSION   # noqa: E402

CFG_SHA = PR.config_sha256()
ID_HASHES = AP.id_set_hashes(CFG)
EXPLORE_IDS = json.loads((ROOT / "evidence" / "week2" / CFG["sets"]["explore"]["file"]).read_text(encoding="utf-8"))["ids"]
SCOPE_NOW = AP.scope_hashes()


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout.strip()


def _frozen(**over):
    f = {"version": "v4", "config_sha256": CFG_SHA, "features_version": FEATURES_VERSION, "explore_ids": list(EXPLORE_IDS), "n_explore": len(EXPLORE_IDS),
         "pool_gate": {"best_arm": "B-expert", "best_rate": 0.75, "threshold": CFG["pool"]["gate"]["threshold"], "decision": "진행"}, "a_hat": "B-expert"}
    f.update(over)
    return f


def _repo(tmp_path, frozen: dict, policy_in_commit: bool = True):
    """임시 git 저장소: 커밋 1 = 정책 없음, 커밋 2 = 동결 정책 포함. (실제 저장소·APPROVAL.json 은 건드리지 않는다)"""
    repo = tmp_path / "repo"; repo.mkdir()
    _git(repo, "init", "-q"); _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "README").write_text("x", encoding="utf-8"); _git(repo, "add", "."); _git(repo, "commit", "-q", "-m", "no policy")
    c1 = _git(repo, "rev-parse", "HEAD")
    fz = repo / "evidence" / "week2" / "pilot_explore" / "frozen_policy.json"; fz.parent.mkdir(parents=True)
    fz.write_text(json.dumps(frozen, ensure_ascii=False, indent=1), encoding="utf-8")
    if policy_in_commit:
        _git(repo, "add", "."); _git(repo, "commit", "-q", "-m", "freeze")
    c2 = _git(repo, "rev-parse", "HEAD")
    return repo, fz, c1, c2


def _approval_doc(fz: Path, commit: str, **over):
    a = {"status": "approved", "stage": "confirm", "reviewer": "codex", "review_ref": "review#L", "freeze_commit": commit, "config_hash": CFG_SHA,
         "policy_hash": hashlib.sha256(fz.read_bytes()).hexdigest(), "feature_extractor_version": FEATURES_VERSION, "id_set_hashes": dict(ID_HASHES),
         "pool_gate": "진행", "scope_files": dict(SCOPE_NOW)}
    a.update(over)
    return a


def _check(tmp_path, approval: dict, fz: Path, repo: Path, stage="confirm"):
    p = tmp_path / "APPROVAL.json"; p.write_text(json.dumps(approval, ensure_ascii=False), encoding="utf-8")
    return AP.check_approval(stage, CFG_SHA, FEATURES_VERSION, ID_HASHES, fz, approval_path=p, repo=repo, cfg=CFG, explore_ids=EXPLORE_IDS, scope_now=SCOPE_NOW)


def test_l2_consistent_freeze_passes_and_explore_stage_separate(tmp_path):
    repo, fz, c1, c2 = _repo(tmp_path, _frozen())
    a = _check(tmp_path, _approval_doc(fz, c2), fz, repo)
    assert a["reviewer"] == "codex"
    ex = _approval_doc(fz, None, stage="explore", policy_hash=None, pool_gate=None)
    assert _check(tmp_path, ex, None, repo, stage="explore")["stage"] == "explore"
    with pytest.raises(AP.ApprovalError, match="stage"):
        _check(tmp_path, ex, fz, repo, stage="confirm")


@pytest.mark.parametrize("a_over,msg", [
    ({"status": "unapproved_draft"}, "approved 아님"),
    ({"freeze_commit": None}, "freeze_commit 없음"),
    ({"policy_hash": "0" * 64}, "policy_hash"),
    ({"pool_gate": "보류"}, "관문"),
    ({"config_hash": "f" * 64}, "config_hash"),
    ({"freeze_commit": "0123456789abcdef0123456789abcdef01234567"}, "git 이력에 없다"),
    ({"id_set_hashes": {**ID_HASHES, "confirm": "x"}}, "id_set_hashes\[confirm\]"),
    ({"feature_extractor_version": "features-i0"}, "feature_extractor_version"),
    ({"reviewer": ""}, "reviewer 비어 있음"),
    ({"review_ref": None}, "review_ref 비어 있음"),
    ({"scope_files": None}, "scope_files 없음"),
    ({"scope_files": {**SCOPE_NOW, "benchmark/arms.py": "0" * 64}}, "승인 이후 실행 관련 파일 변경"),
    ({"scope_files": {**SCOPE_NOW, "benchmark/agents_single.py": "0" * 64}}, "승인 이후 실행 관련 파일 변경"),   # M4: 실제 시스템 프롬프트 파일
])
def test_l2_approval_doc_mismatch_rejected(tmp_path, a_over, msg):
    repo, fz, c1, c2 = _repo(tmp_path, _frozen())
    with pytest.raises(AP.ApprovalError, match=msg):
        _check(tmp_path, _approval_doc(fz, c2, **a_over), fz, repo)


@pytest.mark.parametrize("f_over,msg", [
    ({"config_sha256": "e" * 64}, "동결 파일 config_sha256"),
    ({"features_version": "features-i0"}, "동결 파일 features_version"),
    ({"pool_gate": {"best_arm": "B-expert", "best_rate": 0.85, "threshold": 0.8, "decision": "보류"}}, "관문"),
    ({"pool_gate": {"best_arm": "B-expert", "best_rate": 0.85, "threshold": 0.8, "decision": "진행"}}, "수치.*안 맞다"),
    ({"pool_gate": {"best_arm": "B-expert", "best_rate": 0.75, "threshold": 0.9, "decision": "진행"}}, "등록 문턱"),
    ({"explore_ids": EXPLORE_IDS[:-1] + ["BigCodeBench/9999"]}, "explore_ids"),
    ({"n_explore": 99}, "n_explore"),
])
def test_l2_frozen_file_mismatch_rejected(tmp_path, f_over, msg):
    """승인 문서는 전부 현재 값이고 동결 파일만 옛 설정/추출기/관문/탐색 집합 → 거부."""
    repo, fz, c1, c2 = _repo(tmp_path, _frozen(**f_over))
    with pytest.raises(AP.ApprovalError, match=msg):
        _check(tmp_path, _approval_doc(fz, c2), fz, repo)


def test_l2_freeze_commit_without_policy_or_stale_blob_rejected(tmp_path):
    repo, fz, c1, c2 = _repo(tmp_path, _frozen())
    with pytest.raises(AP.ApprovalError, match="동결 산출물 미포함 커밋"):       # 정책이 없는 임의 조상 커밋
        _check(tmp_path, _approval_doc(fz, c1), fz, repo)
    fz.write_text(json.dumps(_frozen(a_hat="A-self"), ensure_ascii=False, indent=1), encoding="utf-8")   # 커밋 뒤 파일이 바뀜
    with pytest.raises(AP.ApprovalError, match="blob 이 현재 파일과 다르다"):
        _check(tmp_path, _approval_doc(fz, c2), fz, repo)


def test_committed_approval_is_still_a_draft_and_real_stage_all_is_refused():
    a = json.loads(AP.APPROVAL.read_text(encoding="utf-8"))
    assert a["status"] == "unapproved_draft" and a["scope_files"] is None
    p = subprocess.run([sys.executable, "-X", "utf8", "scripts/pilot_dryrun.py", "--backend", "anthropic", "--stage", "all", "--out", "x"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode != 0 and "--stage all 금지" in p.stderr
    assert all((ROOT / f).exists() for f in AP.SCOPE)


# ── Week2-L4: post 정책의 B-solo 선택 비용 ─────────────────────────────────
def test_l4_post_policy_pays_s0_even_when_choosing_b_solo():
    import numpy as np
    import gap_analysis as G
    tasks = ["t0", "t1"]
    C = np.full((2, 6), 0.002); C[:, G.ARMS.index("B-solo")] = 0.005; C[:, G.ARMS.index("T")] = 0.0
    rows = [{"task_id": t, "s0_cost_usd": 0.003, "s0_verify_wall_ms": 100} for t in tasks]
    bsolo = G.ARMS.index("B-solo")
    r = PD.deploy_cost(rows, tasks, C, pick=np.array([bsolo, bsolo]), a_hat=bsolo)
    assert abs(r["policy_deploy_usd_per_task"] - 0.008) < 1e-12 and abs(r["fixed_deploy_usd_per_task"] - 0.005) < 1e-12
    assert r["policy_usd_per_task"] == 0.005 and r["state_acquisition_usd_per_task"] == 0.003 and r["fixed_deploy_includes_s0"] is False
    r2 = PD.deploy_cost(rows, tasks, C, pick=np.array([G.ARMS.index("A-self"), G.ARMS.index("T")]), a_hat=G.ARMS.index("B-expert"))
    assert abs(r2["policy_deploy_usd_per_task"] - (0.002 + 0.003 + 0.0 + 0.003) / 2) < 1e-12        # A-self+s0, T+s0
    assert abs(r2["fixed_deploy_usd_per_task"] - 0.005) < 1e-12 and r2["fixed_deploy_includes_s0"] is True   # B-expert 0.002 + s0 0.003
    rows[1]["s0_cost_usd"] = None                                                                     # 미측정 전파
    r3 = PD.deploy_cost(rows, tasks, C, pick=np.array([bsolo, bsolo]), a_hat=bsolo)
    assert r3["policy_deploy_usd_per_task"] is None and r3["state_acquisition_usd_per_task"] is None and r3["fixed_deploy_usd_per_task"] == 0.005 and r3["n_unpriced"] == 1


# ── Week2-M4: 승인 범위와 실제 실행 설정 연결 ────────────────────────────────
MOCK_EXTRA = {"HARMONET_MODEL_BUILDER": "claude-haiku-4-5", "HARMONET_MODEL_REVIEWER": "claude-sonnet-4-6"}


def test_m4_prompt_file_is_in_scope():
    assert "benchmark/agents_single.py" in AP.SCOPE and (ROOT / "benchmark/agents_single.py").exists()


@pytest.mark.parametrize("var,val", [("HARMONET_BCB_IMAGE", "bigcodebench/bigcodebench-evaluate:latest"), ("HARMONET_BCB_TIMEOUT_S", "5"),
                                     ("HARMONET_BCB_MARGIN_S", "1"), ("ANTHROPIC_MAX_TOKENS", "1024"), ("ANTHROPIC_TEMPERATURE", "0.9"),
                                     ("HARMONET_BUDGET_CAP", "100"), ("HARMONET_MODEL_BUILDER", "claude-opus-4-1")])
def test_m4_conflicting_parent_env_is_refused_before_any_call(monkeypatch, var, val):
    monkeypatch.setenv(var, val)
    with pytest.raises(PD.Gate, match="승인된 설정과 다르다"):
        PD._env("anthropic", "pilot_explore", CFG, {})
    with pytest.raises(PD.Gate):                                             # mock 경로도 같은 규칙 (모델 이름만 시나리오 mock 값)
        PD._env("mock-scenario", "pilot_explore", CFG, MOCK_EXTRA if var != "HARMONET_MODEL_BUILDER" else {**MOCK_EXTRA})


def test_m4_effective_env_equals_config_when_no_conflict(monkeypatch):
    for k in ("HARMONET_BCB_IMAGE", "HARMONET_BCB_TIMEOUT_S", "HARMONET_BCB_MARGIN_S", "ANTHROPIC_MAX_TOKENS", "ANTHROPIC_TEMPERATURE", "HARMONET_BUDGET_CAP"):
        monkeypatch.delenv(k, raising=False)
    env = PD._env("anthropic", "pilot_explore", CFG, {})
    eff = PD.effective_env(env)
    assert eff["HARMONET_BCB_IMAGE"] == CFG["grading"]["image"] == env["HARMONET_BCB_IMAGE"] and float(env["HARMONET_BCB_TIMEOUT_S"]) == CFG["grading"]["timeout_s"]
    assert env["ANTHROPIC_MAX_TOKENS"] == str(CFG["models"]["max_tokens"]) and env["HARMONET_MODEL_BUILDER"] == CFG["models"]["A"] and env["HARMONET_BUDGET_ID"] == CFG["ledger_id"]
    env_m = PD._env("mock-scenario", "pilot_explore", CFG, MOCK_EXTRA)          # mock: 모델 이름은 시나리오 값, 나머지는 설정
    assert env_m["HARMONET_MODEL_BUILDER"] == "claude-haiku-4-5" and env_m["HARMONET_BCB_IMAGE"] == CFG["grading"]["image"]
    monkeypatch.setenv("HARMONET_BCB_TIMEOUT_S", "241.0")                     # 같은 값(수치 동등)은 충돌이 아니다
    assert PD.effective_env(PD._env("anthropic", "pilot_explore", CFG, {}))["HARMONET_BCB_TIMEOUT_S"] == "241.0"
    import harmonet.verify as V
    monkeypatch.setattr(V, "BCB_IMAGE_DEFAULT", "other@sha256:0")            # 코드 기본값이 설정과 다르면 단일 출처 위반
    with pytest.raises(PD.Gate, match="단일 출처"):
        PD._env("anthropic", "pilot_explore", CFG, {})


def test_m4_cli_refuses_env_conflict_before_docker_or_calls():
    import os
    env = dict(os.environ, HARMONET_BCB_IMAGE="bigcodebench/bigcodebench-evaluate:latest")
    p = subprocess.run([sys.executable, "-X", "utf8", "scripts/pilot_dryrun.py", "--backend", "mock-scenario", "--stage", "s0", "--out", "x"],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode != 0 and "승인된 설정과 다르다" in p.stderr and "HARMONET_BCB_IMAGE" in p.stderr
