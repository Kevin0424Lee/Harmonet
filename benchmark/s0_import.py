"""
benchmark/s0_import.py — 파일럿 s0 준비 (Week2-I2 → K3). 탐색 ID 파일의 source 로 분기:
  probe_reuse → 프로브 A-solo 산출물을 그대로 가져온다 (LLM 호출 0, 가시 검증만 현행 버전으로 다시 돌린다, 공식 이미지)
  new         → arms.make_s0 로 생성한다 (유료 경로: 원장 예약·확정)
가져온 s0 는 check_imported 로 원 후보·프롬프트·모델 ID·설정·토큰 출처·역사적 취득 비용 보존을 대조한다.

근거(PREREG_pilot.md §1): 프로브 4 A arm = claude-haiku-4-5-20251001, complete_prompt, temp 0.2, max_tokens 4096, 시스템 프롬프트 동일 → 파일럿 s0 와 같은 설정.
D2 채점기 재채점 뒤집힘 0. `pool_probe_bcb_A.json` 행에 candidate_code·토큰·$ 가 있으므로 build 비용도 그대로 옮긴다 (shared_s0_cost).

    python -X utf8 -m benchmark.s0_import --probe evidence/week2/pool_probe_bcb_A.json --ids evidence/week2/pilot_explore_ids_bcb.json --run-id pilot_explore
      [--generate]   # new 도 생성한다 (백엔드·원장 환경변수 필요). 없으면 probe_reuse 만 가져온다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from benchmark.agents_single import _DEFAULT_SYSTEM
from benchmark.arms import S0_FILES, _s0_hash, _safe, make_s0_guarded
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


def check_imported(d: Path, row: dict, task) -> dict:
    """가져온 s0 가 프로브 원본을 보존하는지 대조 (K3). 불일치는 예외."""
    ctx = json.loads((d / "prompt_context.json").read_text(encoding="utf-8"))
    art = (d / "artifact.py").read_text(encoding="utf-8").rstrip("\n")
    checks = {"candidate": art == row["candidate_code"].rstrip("\n"), "prompt": ctx["task_prompt"] == task.prompt, "model_id": ctx["model_a"] == row["model"],
              "system_prompt": ctx["system_prompt"] == _DEFAULT_SYSTEM, "extraction": ctx["extraction"] == row["extraction"],
              "token_source": ctx["build_cost"]["source"] == row["token_source"] == "measured",
              "tokens": (ctx["build_cost"]["prompt_tokens"], ctx["build_cost"]["completion_tokens"]) == (row["prompt_tokens"], row["completion_tokens"]),
              "historical_cost": ctx["build_cost_usd"] == row["cost_usd"], "imported_from": ctx.get("imported_from") == row.get("trace_path"),
              "hash": (d / "sha256.txt").read_text(encoding="utf-8").strip() == _s0_hash(d)}
    bad = [k for k, v in checks.items() if not v]
    if bad:
        raise RuntimeError(f"[s0_import] 가져온 s0 가 원본과 다르다 {task.task_id}: {bad}")
    return checks


def prepare(ids_doc: dict, probe_rows: dict, root: Path, generate: bool, client_a=None, budget=None, log=print) -> dict:
    """source 별 분기. 반환 {imported: [...], generated: [...], skipped_new: [...], failed: []} — 실패는 예외로 즉시 멈춘다(조용히 넘기지 않음)."""
    ids = ids_doc["ids"]
    sources = ids_doc.get("sources")
    if sources is None or set(sources) != set(ids) or not set(sources.values()) <= {"probe_reuse", "new"}:
        raise RuntimeError("[s0_import] ID 파일에 source(probe_reuse|new) 가 전부 있어야 한다 (benchmark.pilot_split 재실행)")
    tasks = {t.task_id: t for t in load_bcb(ids)}
    out = {"imported": [], "generated": [], "skipped_new": [], "failed": []}
    for k, tid in enumerate(ids, 1):
        if sources[tid] == "probe_reuse":
            if tid not in probe_rows:
                raise RuntimeError(f"[s0_import] 프로브에 없는 id: {tid}")
            d = import_s0(probe_rows[tid], tasks[tid], root)
            check_imported(d, probe_rows[tid], tasks[tid])
            out["imported"].append(tid)
            log(f"[s0_import] {k}/{len(ids)} {tid} import → {d}")
        elif generate:
            t = tasks[tid]
            spec_visible = {kk: v for kk, v in t.spec(visible=True).items() if kk != "hidden_tests"}
            d, created = make_s0_guarded(tid, t.prompt, spec_visible, client_a, budget, root, source="new")   # M2: 실패 기록·fail-closed 는 공통 경계에서
            if json.loads((d / "prompt_context.json").read_text(encoding="utf-8")).get("imported_from") is not None:
                raise RuntimeError(f"[s0_import] new 인데 가져온 s0 가 있다: {tid}")
            out["generated"].append(tid)
            log(f"[s0_import] {k}/{len(ids)} {tid} generate ({'new' if created else 'reused'}) → {d}")
        else:
            out["skipped_new"].append(tid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--generate", action="store_true", help="source=new 도 생성한다 (유료 경로, 원장 필요)")
    ap.add_argument("--summary", default=None, help="결과 JSON 경로")
    args = ap.parse_args()
    rows = {r["task_id"]: r for r in json.loads(Path(args.probe).read_text(encoding="utf-8"))["rows"]}
    ids_doc = json.loads(Path(args.ids).read_text(encoding="utf-8"))
    root = Path(os.getenv("HARMONET_ARMS_ROOT") or (Path(__file__).resolve().parent.parent / "evidence" / "week2")) / args.run_id
    client_a = budget = None
    if args.generate:
        from benchmark.runloop import require_budget
        from harmonet.budget import budget_from_env
        from harmonet.llm import get_llm_client
        budget = budget_from_env(os.getenv("HARMONET_BUDGET_ID") or args.run_id)
        require_budget(budget)
        client_a = get_llm_client("builder")
    out = prepare(ids_doc, rows, root, args.generate, client_a, budget, log=lambda m: print(m, flush=True))
    summary = {k: len(v) for k, v in out.items()}
    print(f"[s0_import] {summary}")
    if args.summary:
        Path(args.summary).write_text(json.dumps({**summary, **out}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
