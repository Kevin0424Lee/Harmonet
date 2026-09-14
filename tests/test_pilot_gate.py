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


# ── Week2-K1: 승인 기록 대조 (파일 존재가 아니라 값) ─────────────────────
import hashlib   # noqa: E402
import approval as AP   # noqa: E402
from benchmark.features import FEATURES_VERSION   # noqa: E402

CFG_SHA = PR.config_sha256()
ID_HASHES = AP.id_set_hashes(CFG)
HEAD = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True).stdout.strip()


def _approval(tmp_path, **over):
    fz = tmp_path / "frozen_policy.json"
    if not fz.exists():
        fz.write_text('{"a_hat": "B-expert"}', encoding="utf-8")
    a = {"status": "approved", "stage": "confirm", "reviewer": "codex", "review_ref": "review#k", "freeze_commit": HEAD, "config_hash": CFG_SHA,
         "policy_hash": hashlib.sha256(fz.read_bytes()).hexdigest(), "feature_extractor_version": FEATURES_VERSION, "id_set_hashes": dict(ID_HASHES), "pool_gate": "진행"}
    a.update(over)
    p = tmp_path / "APPROVAL.json"
    p.write_text(json.dumps(a), encoding="utf-8")
    return p, fz


@pytest.mark.parametrize("over,msg", [
    ({"status": "unapproved_draft"}, "approved 아님"),
    ({"freeze_commit": None}, "freeze_commit 없음"),
    ({"policy_hash": "0" * 64}, "policy_hash"),
    ({"pool_gate": "보류"}, "pool_gate"),
    ({"config_hash": "f" * 64}, "config_hash"),
    ({"freeze_commit": "0123456789abcdef0123456789abcdef01234567"}, "git 이력에 없다"),
    ({"id_set_hashes": {**ID_HASHES, "confirm": "x"}}, "id_set_hashes\[confirm\]"),
    ({"feature_extractor_version": "features-i0"}, "feature_extractor_version"),
])
def test_approval_rejects_each_mismatch(tmp_path, over, msg):
    p, fz = _approval(tmp_path, **over)
    with pytest.raises(AP.ApprovalError, match=msg):
        AP.check_approval("confirm", CFG_SHA, FEATURES_VERSION, ID_HASHES, fz, approval_path=p)


def test_approval_passes_only_when_everything_matches(tmp_path):
    p, fz = _approval(tmp_path)
    a = AP.check_approval("confirm", CFG_SHA, FEATURES_VERSION, ID_HASHES, fz, approval_path=p)
    assert a["reviewer"] == "codex"
    p2, _ = _approval(tmp_path, stage="explore", freeze_commit=None, policy_hash=None, pool_gate=None)
    assert AP.check_approval("explore", CFG_SHA, FEATURES_VERSION, ID_HASHES, None, approval_path=p2)["stage"] == "explore"
    with pytest.raises(AP.ApprovalError, match="stage"):
        AP.check_approval("confirm", CFG_SHA, FEATURES_VERSION, ID_HASHES, fz, approval_path=p2)


def test_committed_approval_is_still_a_draft_and_real_stage_all_is_refused():
    a = json.loads(AP.APPROVAL.read_text(encoding="utf-8"))
    assert a["status"] == "unapproved_draft"
    p = subprocess.run([sys.executable, "-X", "utf8", "scripts/pilot_dryrun.py", "--backend", "anthropic", "--stage", "all", "--out", "x"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode != 0 and "--stage all 금지" in p.stderr
