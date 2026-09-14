"""
benchmark/s0_import.py — 프로브의 A-solo 산출물을 파일럿 s0 스냅샷으로 가져온다 (Week2-I2·I3). LLM 호출 0, 가시 검증만 다시 돌린다(공식 이미지).

근거(PREREG_pilot.md §1): 프로브 4 A arm = claude-haiku-4-5-20251001, complete_prompt, temp 0.2, max_tokens 4096, 시스템 프롬프트 동일 → 파일럿 s0 와 같은 설정.
D2 채점기 재채점 뒤집힘 0. `pool_probe_bcb_A.json` 행에 candidate_code·토큰·$ 가 있으므로 build 비용도 그대로 옮긴다 (shared_s0_cost).

    python -X utf8 -m benchmark.s0_import --probe evidence/week2/pool_probe_bcb_A.json --ids evidence/week2/pilot_explore_ids_bcb.json --run-id pilot_explore
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from benchmark.agents_single import _DEFAULT_SYSTEM
from benchmark.arms import S0_FILES, _s0_hash, _safe
from benchmark.bcb import load_bcb
from benchmark.features import ast_features, error_class
from harmonet.verify import verify_visible


def import_s0(row: dict, task, root: Path) -> Path:
    d = root / _safe(task.task_id) / "s0"
    if (d / "sha256.txt").exists():
        if (d / "sha256.txt").read_text(encoding="utf-8").strip() != _s0_hash(d):
            raise RuntimeError(f"[s0_import] 기존 s0 해시 불일치: {d}")
        return d
    d.mkdir(parents=True, exist_ok=True)
    artifact = row["candidate_code"]
    spec_visible = {k: v for k, v in task.spec(visible=True).items() if k != "hidden_tests"}
    visible = verify_visible(artifact, spec_visible)
    cost = {"prompt_tokens": int(row["prompt_tokens"]), "completion_tokens": int(row["completion_tokens"]), "cache_read_tokens": 0, "cache_write_tokens": 0,
            "llm_calls": 1, "verify_calls": 0, "wall_ms": int(row["wall_ms"]), "source": row["token_source"]}
    (d / "artifact.py").write_text(artifact + "\n", encoding="utf-8")
    (d / "verify_visible.json").write_text(json.dumps(visible, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "prompt_context.json").write_text(json.dumps({"task_id": task.task_id, "task_prompt": task.prompt, "spec_visible": spec_visible,
                                                       "system_prompt": _DEFAULT_SYSTEM, "model_a": row["model"], "extraction": row["extraction"],
                                                       "raw_output_head": "(imported from probe)", "build_cost": cost, "build_cost_usd": row["cost_usd"],
                                                       "wall_ms": int(row["wall_ms"]), "imported_from": row.get("trace_path")}, ensure_ascii=False, indent=1), encoding="utf-8")
    signals = {"outcome": visible["outcome"], "level": visible["level"], "n_run": visible["n_run"], "n_passed": visible["n_passed"], "n_failed": visible["n_failed"],
               "flags": visible["flags"], "applied": visible["applied"], "infra": visible.get("infra", False),
               "error_kinds": sorted(set(w for w in ("SyntaxError", "AssertionError", "TypeError", "NameError", "ImportError", "timeout", "aborted") if w in visible["evidence"])),
               "artifact_chars": len(artifact), "artifact_lines": artifact.count("\n") + 1, "diag_tail": visible["evidence"][-300:],
               "build_tokens": {k: cost[k] for k in ("prompt_tokens", "completion_tokens")}, "build_cost_usd": row["cost_usd"], "build_wall_ms": int(row["wall_ms"]),
               "prompt_chars": len(task.prompt), "budget_refused": False, **{k: v for k, v in ast_features(artifact).items() if k != "ast_ok"},
               "error_class": error_class(visible["evidence"][-300:])}
    (d / "decision_signals.json").write_text(json.dumps(signals, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "sha256.txt").write_text(_s0_hash(d), encoding="utf-8")
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    rows = {r["task_id"]: r for r in json.loads(Path(args.probe).read_text(encoding="utf-8"))["rows"]}
    ids = json.loads(Path(args.ids).read_text(encoding="utf-8"))["ids"]
    if args.limit:
        ids = ids[: args.limit]
    root = Path(os.getenv("HARMONET_ARMS_ROOT") or (Path(__file__).resolve().parent.parent / "evidence" / "week2")) / args.run_id
    tasks = {t.task_id: t for t in load_bcb(ids)}
    for k, tid in enumerate(ids, 1):
        if tid not in rows:
            raise SystemExit(f"[s0_import] 프로브에 없는 id: {tid}")
        d = import_s0(rows[tid], tasks[tid], root)
        print(f"[s0_import] {k}/{len(ids)} {tid} → {d}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
