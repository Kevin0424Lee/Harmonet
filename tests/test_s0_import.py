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
