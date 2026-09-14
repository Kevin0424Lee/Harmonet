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
        PD.gate_common(_args(), CFG, IDS_OK, tmp_path, "confirm")


def test_backend_and_stage_have_no_default():
    p = subprocess.run([sys.executable, "-X", "utf8", "scripts/pilot_dryrun.py", "--out", "x"], cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode == 2 and "--backend" in p.stderr and "--stage" in p.stderr
