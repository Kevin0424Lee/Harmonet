"""
scripts/pilot_dryrun.py — 파일럿 종단간 한 명령 (Week2-I3). 기본은 무유료 dry-run(시나리오 mock, 실제 Docker 채점); `--backend anthropic` 이면 실제 파일럿
(PREREG_pilot.md 승인 뒤에만). 두 모드는 **백엔드 환경변수만** 다르다.

단계: (1) [dry-run] 시나리오 mock 작성 → (2) arms.py k=1, 6 arm (+ 뒤집힘 부분집합 A-self·B-expert k=2) → (3) s0/decision_signals + 산출물에서 pre/post 특징 추출 →
(4) gap_analysis: P2-post(주) · P2-pre · P1, 특징 순열 2000, 과제 부트스트랩 1000 → (5) PREREG §4 보고 항목 1:1 로 JSON + Markdown.

    python -X utf8 scripts/pilot_dryrun.py --out evidence/week2/pilot_dryrun            # dry-run (6 개발용 과제)
    python -X utf8 scripts/pilot_dryrun.py --backend anthropic --ids evidence/week2/pilot_explore_ids_bcb.json --run-id pilot_explore --out …  # 실제 (승인 후)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import gap_analysis as G                                        # noqa: E402
from benchmark.features import FEATURE_SPECS, P2_CONFIG, task_features  # noqa: E402

DRY_IDS = ["BigCodeBench/0", "BigCodeBench/1", "BigCodeBench/2", "BigCodeBench/3", "BigCodeBench/4", "BigCodeBench/9"]   # 개발용 (풀 제외)
DRY_SCRIPTS = {  # 과제마다 다른 변형 → post 특징·히든 결과가 갈린다
    "BigCodeBench/0": {"s0": "near", "A-self": "correct", "A-role": "wrong", "B-expert": "correct", "B-solo": "wrong"},
    "BigCodeBench/1": {"s0": "wrong", "A-self": "wrong", "A-role": "correct", "B-expert": "correct", "B-solo": "correct"},
    "BigCodeBench/2": {"s0": "correct", "A-self": "correct", "A-role": "correct", "B-expert": "wrong", "B-solo": "wrong"},
    "BigCodeBench/3": {"s0": "near", "A-self": "wrong", "A-role": "near", "B-expert": "correct", "B-solo": "correct"},
    "BigCodeBench/4": {"s0": "wrong", "A-self": "near", "A-role": "correct", "B-expert": "wrong", "B-solo": "correct"},
    "BigCodeBench/9": {"s0": "correct", "A-self": "wrong", "A-role": "near", "B-expert": "near", "B-solo": "near"},
}


def _env(backend: str, run_id: str, cap: str, extra: dict) -> dict:
    env = dict(os.environ, HARMONET_LLM_BACKEND=backend, HARMONET_ALLOW_NO_REDIS="1", HARMONET_TRACE_RUN_ID=run_id, HARMONET_BUDGET_CAP=cap,
               ANTHROPIC_MAX_TOKENS="4096", ANTHROPIC_TEMPERATURE="0.2", PYTHONIOENCODING="utf-8", **extra)
    if backend == "anthropic":
        env["HARMONET_MODEL_BUILDER"], env["HARMONET_MODEL_REVIEWER"] = "claude-haiku-4-5", "claude-sonnet-4-6"
        env["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "")
    return env


def run_arms(ids_file: Path, out: Path, env: dict, k: int, arms: str, b_cont: float, a_med: float) -> dict:
    cmd = [sys.executable, "-X", "utf8", "-m", "benchmark.arms", "--pool", "bcb", "--ids", str(ids_file), "--output", str(out), "--b-cont", str(b_cont),
           "--a-call-median", str(a_med), "--k", str(k), "--arms", arms]
    rc = subprocess.run(cmd, cwd=str(ROOT), env=env).returncode
    if rc != 0:
        raise SystemExit(f"[dryrun] arms 종료 코드 {rc} (부분 결과 {out})")
    return json.loads(out.read_text(encoding="utf-8"))


def rows_with_features(arms_out: dict, arms_root: Path, run_id: str):
    rows = []
    for r in arms_out["rows"]:
        if r["rep"] != 1:
            continue
        s0 = Path(r["s0_dir"])
        ctx = json.loads((s0 / "prompt_context.json").read_text(encoding="utf-8"))
        sig = json.loads((s0 / "decision_signals.json").read_text(encoding="utf-8"))
        code = (s0 / "artifact.py").read_text(encoding="utf-8")
        f = task_features(ctx["task_prompt"], sig, code, ctx["spec_visible"].get("entry_point", "task_func"))
        rows.append({**{k: r[k] for k in ("task_id", "arm", "rep", "hidden_pass", "cost_usd", "budget_refused", "infra", "hidden_exposed")}, "features": f})
    return rows


def ledger_state(env: dict, run_id: str) -> dict:
    """총지출은 계산하지 않고 원장에서 읽는다 (J1): 주 실행·뒤집힘 부분집합·0회차가 같은 run_id 원장에 쌓인다."""
    root = Path(env.get("HARMONET_BUDGET_ROOT") or (ROOT / "evidence" / "week2"))
    p = root / (env.get("HARMONET_BUDGET_ID") or run_id) / "budget.json"
    if not p.exists():
        raise RuntimeError(f"[dryrun] 원장이 없다: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def spend_report(env: dict, run_id: str, outs: list) -> dict:
    """보고서 총지출 = 원장 spent. 교차 검산: 원장 == Σ arm 단독 + 이 원장에서 만든 s0 (프로브에서 가져온 s0 의 원 생성비는 역사적 취득 비용으로 별도 표기).
    불일치는 예외 — 조용히 넘기지 않는다."""
    led = ledger_state(env, run_id)
    # arm 단독 비용은 (task, arm, rep) 로 중복 제거해 더한다 — 뒤집힘 부분집합 실행은 주 실행의 rep1 result.json 을 재사용하므로 출력별 합계를 더하면 이중 계상
    # (J1 dry-run 에서 원장 검산이 잡아낸 것: $0.2465 vs 원장 $0.2117 = 재사용 rep1 6행 만큼 차이).
    cells = {(r["task_id"], r["arm"], r["rep"]): r["cost_usd"] for o in outs for r in o["rows"]}
    own = None if any(v is None for v in cells.values()) else round(sum(cells.values()), 8)
    s0_here, s0_hist, seen = 0.0, 0.0, set()
    for o in outs:
        for r in o["rows"]:
            if r["task_id"] in seen:
                continue
            seen.add(r["task_id"])
            ctx = json.loads((Path(r["s0_dir"]) / "prompt_context.json").read_text(encoding="utf-8"))
            c = o["shared_s0_cost"][r["task_id"]]
            if c is None:
                s0_here = None if ctx.get("imported_from") is None else s0_here
                continue
            if ctx.get("imported_from") is None:
                s0_here = None if s0_here is None else s0_here + c
            else:
                s0_hist += c
    n_unpriced = sum(v is None for v in cells.values())
    expected = None if (own is None or s0_here is None) else own + s0_here
    if expected is not None and abs(expected - led["spent"]) > 1e-6:
        raise RuntimeError(f"[dryrun] 보고서 총지출 {expected:.8f} != 원장 총지출 {led['spent']:.8f} (arm 단독 {own}, s0 여기서 생성 {s0_here})")
    rep = {"total_spent_usd": led["spent"], "source": "ledger", "ledger": {"cap": led["cap"], "spent": led["spent"], "n_calls": led["n_calls"],
           "stopped_reason": led["stopped_reason"]}, "arms_own_usd": own, "n_cells": len(cells), "s0_built_here_usd": s0_here, "s0_imported_historical_usd": round(s0_hist, 8),
           "n_unpriced": n_unpriced, "check": "ledger == Σ arms_own + s0_built_here" if expected is not None else "미측정 있음 — 검산 불가"}
    assert rep["total_spent_usd"] == led["spent"]
    return rep


def oracle_descriptive(rows):
    S, tasks, reps = G.tensor(rows)
    M = S[:, :, 0]
    return {"oracle_minus_fixed_insample": float(M.max(axis=1).mean() - M.mean(axis=0).max()), "note": "기술 통계 — 상한 아님 (G1~G3)"}


def flip_rates(flip_out: dict):
    by = {}
    for r in flip_out["rows"]:
        by.setdefault((r["task_id"], r["arm"]), {})[r["rep"]] = r["hidden_pass"]
    out = {}
    for arm in ("A-self", "B-expert"):
        cells = [v for (t, a), v in by.items() if a == arm and 1 in v and 2 in v]
        out[arm] = {"n_cells": len(cells), "flip_rate": (sum(v[1] != v[2] for v in cells) / len(cells)) if cells else None}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="mock-scenario", choices=["mock-scenario", "anthropic"])
    ap.add_argument("--ids", default=None)
    ap.add_argument("--flip-ids", default=None)
    ap.add_argument("--run-id", default="pilot_dryrun")
    ap.add_argument("--out", required=True, help="출력 접두 (…json / …md)")
    ap.add_argument("--cap", default="14")
    ap.add_argument("--b-cont", type=float, default=0.02)
    ap.add_argument("--a-call-median", type=float, default=0.003)
    ap.add_argument("--n-perm", type=int, default=P2_CONFIG["n_perm"])
    ap.add_argument("--n-boot", type=int, default=P2_CONFIG["n_boot"])
    ap.add_argument("--workers", type=int, default=14)
    args = ap.parse_args()
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="pilot_"))
    extra = {}
    if args.backend == "mock-scenario":
        from benchmark.mock_scenario import write_bcb_scenario
        sc = tmp / "scenario.json"; write_bcb_scenario(DRY_IDS, DRY_SCRIPTS, sc, tokens={"prompt": 400, "completion": 500})
        ids_file = tmp / "ids.json"; ids_file.write_text(json.dumps({"ids": DRY_IDS}), encoding="utf-8")
        flip_file = tmp / "flip.json"; flip_file.write_text(json.dumps({"ids": DRY_IDS[:3]}), encoding="utf-8")
        extra = {"HARMONET_MOCK_SCENARIO": str(sc), "HARMONET_MODEL_BUILDER": "claude-haiku-4-5", "HARMONET_MODEL_REVIEWER": "claude-sonnet-4-6",
                 "HARMONET_BUDGET_ROOT": str(tmp / "budget"), "HARMONET_ARMS_ROOT": str(tmp / "arms"), "HARMONET_TRACE_DIR": str(tmp / "traces")}
    else:
        if not args.ids:
            raise SystemExit("--ids 필요 (pilot_explore_ids_bcb.json 등)")
        ids_file = Path(args.ids)
        flip_file = Path(args.flip_ids) if args.flip_ids else None
    env = _env(args.backend, args.run_id, args.cap, extra)
    main_out = run_arms(ids_file, tmp / "arms_main.json", env, 1, ",".join(G.ARMS), args.b_cont, args.a_call_median)
    flip_out = run_arms(flip_file, tmp / "arms_flip.json", env, 2, "A-self,B-expert", args.b_cont, args.a_call_median) if flip_file else None
    rows = rows_with_features(main_out, Path(extra.get("HARMONET_ARMS_ROOT", ROOT / "evidence/week2")), args.run_id)
    res = {}
    for name, learner, spec in (("P2-post", "P2", FEATURE_SPECS["post"]), ("P2-pre", "P2", FEATURE_SPECS["pre"]), ("P1", "P1", FEATURE_SPECS["post"])):
        res[name] = G.policy_gain(rows, learner, n_perm=args.n_perm, n_boot=args.n_boot, seed=20260915, spec=spec, workers=args.workers)
    main_r = res["P2-post"]
    verdict = main_r["diag_R2"]                            # 진단 라벨 (J: 판정 규칙 아님). 보고 항목 v4 교체는 J5
    spend = spend_report(env, args.run_id, [o for o in (main_out, flip_out) if o])
    report = {
        "mode": args.backend, "run_id": args.run_id, "n_tasks": main_r["n_tasks"], "verdict_R2": verdict,
        "R2": {"p_value": main_r["p_value"], "gain_P2_post": main_r["gain"], "ci95": main_r.get("ci95"), "threshold": 0.10},
        "secondary": {"gain_P2_pre": res["P2-pre"]["gain"], "p_P2_pre": res["P2-pre"]["p_value"], "post_minus_pre": main_r["gain"] - res["P2-pre"]["gain"],
                      "gain_P1": res["P1"]["gain"], "p_P1": res["P1"]["p_value"], "oracle_gap_descriptive": oracle_descriptive(rows)},
        "arms": main_out["summary"], "cost": spend, "pick_dist_P2_post": main_r["pick_dist"],
        "budget_match": {"policy_usd_per_task": main_r["cost_policy_usd"], "fixed_usd_per_task": main_r["cost_fixed_usd"]},
        "flip": flip_rates(flip_out) if flip_out else None, "config": {**P2_CONFIG, "n_perm": args.n_perm, "n_boot": args.n_boot, "features": FEATURE_SPECS},
        "stopped_reason": main_out.get("stopped_reason"), "elapsed_s": round(time.time() - t0),
    }
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    a = report["arms"]
    md = [f"# 파일럿 보고 ({args.backend}, run_id={args.run_id}, N={report['n_tasks']}, {report['elapsed_s']}s)", "",
          f"## 판정 R2: **{verdict}** — 특징 순열 p = {main_r['p_value']:.3f}, P2-post 이득 = {100 * main_r['gain']:+.1f}pp (CI95 {[round(100 * x, 1) for x in main_r['ci95']]}), 문턱 10pp", "",
          "## 부차", f"- P2-pre 이득 {100 * res['P2-pre']['gain']:+.1f}pp (p {res['P2-pre']['p_value']:.3f}); P2-post − P2-pre = {100 * report['secondary']['post_minus_pre']:+.1f}pp",
          f"- P1 이득 {100 * res['P1']['gain']:+.1f}pp (p {res['P1']['p_value']:.3f}) [진단]", f"- oracle − 고정 (표본 내, 기술 통계) {100 * report['secondary']['oracle_gap_descriptive']['oracle_minus_fixed_insample']:.1f}pp",
          "", "| arm | 히든 성공률 | 거부율 | arm 단독 $ | 호출 수 평균 |", "|---|---|---|---|---|"]
    for arm in G.ARMS:
        if arm in a:
            md.append(f"| {arm} | {100 * a[arm]['hidden_pass']:.1f}% | {100 * a[arm]['refused_rate']:.0f}% | ${a[arm]['cost_own_cost_usd']} | {a[arm]['n_calls_mean']:.1f} |")
    md += ["", f"- 정책이 고른 arm 분포 (P2-post): " + ", ".join(f"{k} {100 * v:.0f}%" for k, v in main_r["pick_dist"].items()),
           f"- 예산 매칭: 정책 ${main_r['cost_policy_usd']:.4f} / 고정 ${main_r['cost_fixed_usd']:.4f} (과제당)",
           f"- 실험 총지출(원장): ${spend['total_spent_usd']} (호출 {spend['ledger']['n_calls']}, arm 단독 {spend['arms_own_usd']}, 여기서 만든 s0 ${spend['s0_built_here_usd']}, "
           f"가져온 s0 원 생성비(역사적) ${spend['s0_imported_historical_usd']}, 미측정 {spend['n_unpriced']}; 검산 {spend['check']})",
           f"- 뒤집힘 부분집합: {json.dumps(report['flip'], ensure_ascii=False)}", f"- 중단 사유: {report['stopped_reason']}"]
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
