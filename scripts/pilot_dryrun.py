"""
scripts/pilot_dryrun.py — 파일럿 v4 (2단계 동결) 종단간 한 명령 (Week2-I3 → J5). 기본은 무유료 dry-run(시나리오 mock, 실제 Docker 채점).
실제 모드는 게이트(J5)를 전부 통과해야만 호출한다 — 하나라도 없으면 Gate(RuntimeError), 호출 0회. 기본값으로 진행하는 경로는 없다(수치는 pilot_config_v4.json 에서만).

탐색(--stage explore): 게이트 → 0회차(B-expert × n_round0, max_tokens 4096 무상한 → b_cont, a_call_median = s0 비용 중앙값) → 6 arm k=1 + 뒤집힘 k=2 →
  풀 관문 → 특징 선택(메뉴 ≤ max_selected)·λ 선택(CV)·P2-post/P2-pre/P1 학습·â → frozen_policy.json (+sha256) → PREREG 보고 항목 1:1 JSON/MD.
확인(--stage confirm): 게이트(+ frozen_policy.json, 확인 ∩ 탐색 = ∅) → 6 arm k=1 → 동결 정책 적용 → gap_analysis.confirm_test (학습 없음) → 보고.
dry-run: 개발용 6 과제 (탐색 4 / 확인 2, 뒤집힘 2, 0회차 2) 로 두 단계를 다 돈다 — 배관 점검이지 통계가 아니다.

    python -X utf8 scripts/pilot_dryrun.py --backend mock-scenario --stage all --out evidence/week2/pilot_dryrun
    python -X utf8 scripts/pilot_dryrun.py --backend anthropic --stage explore --out evidence/week2/pilot_v4    # 승인 후
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import gap_analysis as G                                        # noqa: E402
from benchmark.features import FEATURES_VERSION, FEATURE_SPECS, task_features  # noqa: E402
from prereg_render import CONFIG, PREREG, config_sha256, current_block       # noqa: E402
from approval import ApprovalError, check_approval, id_set_hashes            # noqa: E402

DRY_IDS = ["BigCodeBench/0", "BigCodeBench/1", "BigCodeBench/2", "BigCodeBench/3", "BigCodeBench/4", "BigCodeBench/9"]   # 개발용 (풀 제외)
DRY_SCRIPTS = {  # 과제마다 다른 변형 → post 특징·히든 결과가 갈린다
    "BigCodeBench/0": {"s0": "near", "A-self": "correct", "A-role": "wrong", "B-expert": "correct", "B-solo": "wrong"},
    "BigCodeBench/1": {"s0": "wrong", "A-self": "wrong", "A-role": "correct", "B-expert": "correct", "B-solo": "correct"},
    "BigCodeBench/2": {"s0": "correct", "A-self": "correct", "A-role": "correct", "B-expert": "wrong", "B-solo": "wrong"},
    "BigCodeBench/3": {"s0": "near", "A-self": "wrong", "A-role": "near", "B-expert": "correct", "B-solo": "correct"},
    "BigCodeBench/4": {"s0": "wrong", "A-self": "near", "A-role": "correct", "B-expert": "wrong", "B-solo": "correct"},
    "BigCodeBench/9": {"s0": "correct", "A-self": "wrong", "A-role": "near", "B-expert": "near", "B-solo": "near"},
}


class Gate(RuntimeError):
    """실행 게이트 미충족 — 호출 0회."""


# ── 환경·실행 ─────────────────────────────────────────────────────────────
def governed_env(cfg: dict, backend: str, extra: dict) -> dict:
    """M4: 실행에 적용되는 값의 단일 출처 = 설정 파일. 채점 이미지/digest·timeout·margin·max_tokens·temperature·cap·원장 id·모델 id."""
    g = {"HARMONET_BCB_IMAGE": cfg["grading"]["image"], "HARMONET_BCB_TIMEOUT_S": str(cfg["grading"]["timeout_s"]), "HARMONET_BCB_MARGIN_S": str(cfg["grading"]["margin_s"]),
         "HARMONET_BCB_MEMORY": str(cfg["grading"]["docker"]["memory"]), "HARMONET_BCB_CPUS": str(cfg["grading"]["docker"]["cpus"]),
         "HARMONET_BCB_LIMITS": json.dumps(cfg["grading"]["limits"], sort_keys=True),
         "ANTHROPIC_MAX_TOKENS": str(cfg["models"]["max_tokens"]), "ANTHROPIC_TEMPERATURE": str(cfg["models"]["temperature"]),
         "HARMONET_BUDGET_CAP": str(cfg["cost_usd"]["cap"]), "HARMONET_BUDGET_ID": cfg["ledger_id"]}
    if backend == "anthropic":
        g["HARMONET_MODEL_BUILDER"], g["HARMONET_MODEL_REVIEWER"] = cfg["models"]["A"], cfg["models"]["B"]
    else:                                                    # mock: 모델 이름은 시나리오 mock 이 정한다 (extra), 그 외는 설정과 같다
        g["HARMONET_MODEL_BUILDER"], g["HARMONET_MODEL_REVIEWER"] = extra["HARMONET_MODEL_BUILDER"], extra["HARMONET_MODEL_REVIEWER"]
    return g


def _same(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        pass
    try:
        return json.loads(a) == json.loads(b)                    # HARMONET_BCB_LIMITS 같은 JSON 값 (키 순서 무관)
    except (ValueError, TypeError):
        return a == b


def _env(backend: str, run_id: str, cfg: dict, extra: dict) -> dict:
    """자식 환경 = 부모 환경 + 설정에서 유도한 값. 부모 환경변수가 설정과 **다른 값**을 이미 가지고 있으면 조용히 덮어쓰지 않고 Gate (호출 0) — M4.
    실효 설정은 env["HARMONET_EFFECTIVE_ENV"](JSON) 로 자식에 넘기고 보고서 effective_env 에 기록한다."""
    g = governed_env(cfg, backend, extra)
    conflicts = {k: (os.environ[k], v) for k, v in g.items() if k in os.environ and not _same(os.environ[k], v)}
    if conflicts:
        raise Gate("부모 환경변수가 승인된 설정과 다르다 (조용한 덮어쓰기 금지, 호출 0): " + "; ".join(f"{k}: env={a!r} vs 설정={b!r}" for k, (a, b) in conflicts.items()))
    from harmonet.verify import BCB_CPUS_DEFAULT, BCB_IMAGE_DEFAULT, BCB_LIMITS, BCB_MEMORY_DEFAULT, BCB_TASK_TIMEOUT_S
    if BCB_IMAGE_DEFAULT != cfg["grading"]["image"] or float(BCB_TASK_TIMEOUT_S) != float(cfg["grading"]["timeout_s"]):
        raise Gate(f"코드 기본값(verify.BCB_IMAGE_DEFAULT/BCB_TASK_TIMEOUT_S)이 설정 파일과 다르다 — 단일 출처 위반: {BCB_IMAGE_DEFAULT[:40]}… / {BCB_TASK_TIMEOUT_S}")
    if (BCB_MEMORY_DEFAULT, BCB_CPUS_DEFAULT) != (str(cfg["grading"]["docker"]["memory"]), str(cfg["grading"]["docker"]["cpus"])) or BCB_LIMITS != cfg["grading"]["limits"]:
        raise Gate(f"코드 기본값(verify.BCB_MEMORY/CPUS/LIMITS)이 설정 파일과 다르다 — 단일 출처 위반: {BCB_MEMORY_DEFAULT}/{BCB_CPUS_DEFAULT}/{BCB_LIMITS} vs "
                   f"{cfg['grading']['docker']}/{cfg['grading']['limits']}")
    env = {**os.environ, "HARMONET_LLM_BACKEND": backend, "HARMONET_ALLOW_NO_REDIS": "1", "HARMONET_TRACE_RUN_ID": run_id, "PYTHONIOENCODING": "utf-8", **extra, **g}
    env["HARMONET_EFFECTIVE_ENV"] = json.dumps(g)
    return env


def effective_env(env: dict) -> dict:
    """보고용 실효 설정 = 자식 환경에 넘긴 governed 값 + 그 환경에서 verify 가 실제로 읽는 자원·제한값 (N2: 선언과 소비가 같은지 보고서에서 볼 수 있게)."""
    g = json.loads(env["HARMONET_EFFECTIVE_ENV"])
    saved = {k: os.environ.get(k) for k in ("HARMONET_BCB_MEMORY", "HARMONET_BCB_CPUS", "HARMONET_BCB_LIMITS", "HARMONET_BCB_IMAGE")}
    try:
        os.environ.update({k: env[k] for k in saved})
        from harmonet.verify import bcb_container_args, bcb_limits, bcb_resources
        args = bcb_container_args("/w", "harness.py")
        g["_effective_docker"] = {"resources": bcb_resources(), "limits": bcb_limits(), "container_args": args}
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return g


def run_arms(ids_file: Path, out: Path, env: dict, k: int, arms: str, b_cont: float, a_med: float) -> dict:
    cmd = [sys.executable, "-X", "utf8", "-m", "benchmark.arms", "--pool", "bcb", "--ids", str(ids_file), "--output", str(out), "--b-cont", str(b_cont),
           "--a-call-median", str(a_med), "--k", str(k), "--arms", arms]
    rc = subprocess.run(cmd, cwd=str(ROOT), env=env).returncode
    if rc != 0:
        raise SystemExit(f"[pilot] arms 종료 코드 {rc} (부분 결과 {out})")
    return json.loads(out.read_text(encoding="utf-8"))


def rows_with_features(arms_out: dict):
    rows = []
    for r in arms_out["rows"]:
        if r["rep"] != 1:
            continue
        s0 = Path(r["s0_dir"])
        ctx = json.loads((s0 / "prompt_context.json").read_text(encoding="utf-8"))
        sig = json.loads((s0 / "decision_signals.json").read_text(encoding="utf-8"))
        code = (s0 / "artifact.py").read_text(encoding="utf-8")
        f = task_features(ctx["task_prompt"], sig, code, ctx["spec_visible"].get("entry_point", "task_func"))
        vis = json.loads((s0 / "verify_visible.json").read_text(encoding="utf-8"))
        rows.append({**{k: r[k] for k in ("task_id", "arm", "rep", "hidden_pass", "cost_usd", "budget_refused", "infra", "hidden_exposed")}, "features": f,
                     "s0_cost_usd": sig["build_cost_usd"], "s0_verify_wall_ms": int(vis.get("wall_ms", 0))})     # K5: 상태 취득 비용 (s0 + 가시 검증)
    return rows


# ── 원장 총지출 (J1) ──────────────────────────────────────────────────────
def ledger_state(env: dict) -> dict:
    root = Path(env.get("HARMONET_BUDGET_ROOT") or (ROOT / "evidence" / "week2"))
    p = root / env["HARMONET_BUDGET_ID"] / "budget.json"
    if not p.exists():
        raise RuntimeError(f"[pilot] 원장이 없다: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def spend_report(env: dict, outs: list, round0_usd: float, prior_usd: float = 0.0) -> dict:
    """보고서 총지출 = 원장 spent. 검산: 원장 == prior(앞 단계) + 0회차 + Σ arm 단독(셀 중복 제거) + 여기서 만든 s0. 가져온 s0 원 생성비는 역사적 취득 비용.
    불일치는 예외 — 조용히 넘기지 않는다. (J1 dry-run 검산이 잡은 것: 뒤집힘 실행이 주 실행 rep1 result.json 을 재사용해 출력별 합계는 이중 계상)"""
    led = ledger_state(env)
    cells = {(r["task_id"], r["arm"], r["rep"]): r["cost_usd"] for o in outs for r in o["rows"]}
    own = None if any(v is None for v in cells.values()) else round(sum(cells.values()), 8)
    s0_here, s0_hist, seen = 0.0, 0.0, set()
    for o in outs:
        for tid, c in o["shared_s0_cost"].items():        # 과제 단위 (행이 없는 과제 — s0 뒤 중단 — 도 s0 비용은 원장에 있다, L5)
            if tid in seen or c is None and not o["s0_dirs"].get(tid):
                continue
            seen.add(tid)
            s0d = o["s0_dirs"].get(tid)
            ctx = json.loads((Path(s0d) / "prompt_context.json").read_text(encoding="utf-8")) if s0d and (Path(s0d) / "prompt_context.json").exists() else {}
            if ctx.get("imported_from") is None:
                s0_here = None if (c is None or s0_here is None) else s0_here + c
            else:
                s0_hist += c or 0.0
    n_unpriced = sum(v is None for v in cells.values())
    inc = {i["path"]: i for o in outs for i in o.get("incomplete_arms", [])}          # L5: 미완료 arm 에피소드 (경로로 유일 — 이중 계상 없음)
    _sum = lambda vals: (None if any(v is None for v in vals) else round(sum(vals), 10))   # M3: None 은 0 이 아니다
    inc_usd = _sum([i["cost_usd"] for i in inc.values()])
    by_cell = {(r["task_id"], r["arm"], r["rep"]): r for o in outs for r in o["rows"]}   # 실측/귀속도 셀 중복 제거 (뒤집힘 실행의 rep1 재사용)
    measured = _sum([r.get("cost_measured_usd", 0.0) for r in by_cell.values()] + [i["measured_usd"] for i in inc.values()])
    unknown = _sum([r.get("cost_unknown_reserved_usd", 0.0) for r in by_cell.values()] + [i["unknown_reserved_usd"] for i in inc.values()])
    expected = None if (own is None or s0_here is None or inc_usd is None) else prior_usd + round0_usd + own + s0_here + inc_usd
    if expected is not None and abs(expected - led["spent"]) > 1e-6:
        raise RuntimeError(f"[pilot] 보고서 총지출 {expected:.8f} != 원장 총지출 {led['spent']:.8f} (prior {prior_usd}, round0 {round0_usd}, arm {own}, s0 {s0_here}, incomplete {inc_usd})")
    rep = {"total_spent_usd": led["spent"], "source": "ledger", "ledger": {"cap": led["cap"], "spent": led["spent"], "n_calls": led["n_calls"], "stopped_reason": led["stopped_reason"],
                                                                             "unknown_cost_calls": led.get("unknown_cost_calls", 0), "unbilled_failed_calls": led.get("unbilled_failed_calls", 0)},
           "prior_stage_usd": prior_usd, "round0_usd": round0_usd, "arms_own_usd": own, "n_cells": len(cells), "s0_built_here_usd": s0_here,
           "s0_imported_historical_usd": round(s0_hist, 8), "n_unpriced": n_unpriced,
           "incomplete_usd": inc_usd, "n_incomplete_arms": len(inc), "arms_measured_usd": measured, "arms_unknown_reserved_usd": unknown,
           "note": "arms_measured_usd = 성공 시도 실측 합, arms_unknown_reserved_usd = 처리 여부 불명 시도의 보수적 예약 귀속 합 (실측 청구액 아님); s0/0회차는 별도",
           "check": "ledger == prior + round0 + Σ arms_own + s0_built_here + incomplete" if expected is not None else "미측정 있음 — 검산 불가"}
    assert rep["total_spent_usd"] == led["spent"]
    return rep


# ── 게이트 (J5) ──────────────────────────────────────────────────────────
def gate_common(args, cfg: dict, ids: dict, arms_root: Path, stage: str) -> dict:
    """실제 모드 조건 전부. dry-run 도 같은 코드를 지나되 s0 가져오기 조건은 probe_reuse_ids 가 빈 목록이라 공허하게 참."""
    checks = {}
    if args.backend not in ("mock-scenario", "anthropic"):
        raise Gate(f"--backend 를 명시해야 한다 ({args.backend!r})")
    checks["backend_explicit"] = args.backend
    m = current_block(PREREG.read_text(encoding="utf-8"))
    sha = config_sha256(CONFIG)
    if m is None or sha not in m.group(0):
        raise Gate(f"PREREG_pilot_v4.md 가 가리키는 설정 해시 ≠ pilot_config_v4.json ({sha[:12]}) — scripts/prereg_render.py 로 갱신 후 커밋")
    checks["config_sha256"] = sha
    if "flip_subset_ids" not in ids or len(ids["flip_subset_ids"]) != ids.get("flip_subset_n"):
        raise Gate("뒤집힘 부분집합 설정(flip_subset_ids / flip_subset_n)이 탐색 ID 파일에 없다")
    checks["flip_subset_n"] = len(ids["flip_subset_ids"])
    missing = []
    for tid in ids.get("probe_reuse_ids", []):
        d = arms_root / cfg["run_ids"]["explore"] / tid.replace("/", "_") / "s0"
        ok = (d / "sha256.txt").exists() and (d / "prompt_context.json").exists() and \
            json.loads((d / "prompt_context.json").read_text(encoding="utf-8")).get("imported_from") is not None
        if not ok:
            missing.append(tid)
    if missing:
        raise Gate(f"s0 가져오기 미완료 {len(missing)}/{len(ids['probe_reuse_ids'])}: {missing[:3]} … (benchmark.s0_import 먼저)")
    checks["s0_imported"] = len(ids.get("probe_reuse_ids", []))
    if args.backend == "anthropic":                        # K1: 승인 기록 대조 (값 하나하나). dry-run 은 승인 없이 배관만 점검
        fz_path = arms_root / cfg["run_ids"]["explore"] / "frozen_policy.json"
        checks["approval"] = {k: v for k, v in check_approval(stage, sha, FEATURES_VERSION, id_set_hashes(cfg), fz_path, cfg=cfg, explore_ids=ids["ids"]).items()
                              if k in ("reviewer", "review_ref", "freeze_commit")}
    from benchmark.bcb import bcb_preflight
    checks["docker_preflight"] = bcb_preflight()
    if stage == "confirm":
        fz = arms_root / cfg["run_ids"]["explore"] / "frozen_policy.json"
        if not fz.exists() or (fz.with_suffix(".sha256").read_text(encoding="utf-8").strip() != hashlib.sha256(fz.read_bytes()).hexdigest()):
            raise Gate(f"동결 정책이 없거나 해시 불일치: {fz}")
        checks["frozen_policy"] = fz.with_suffix(".sha256").read_text(encoding="utf-8").strip()
    return checks


def gate_round0(round0_path: Path) -> dict:
    if not round0_path.exists():
        raise Gate(f"0회차 b_cont 측정이 없다: {round0_path}")
    r0 = json.loads(round0_path.read_text(encoding="utf-8"))
    if not (isinstance(r0.get("b_cont"), float) and r0["b_cont"] > 0 and isinstance(r0.get("a_call_median"), float) and r0["a_call_median"] > 0):
        raise Gate(f"0회차 파일이 불완전하다: {r0}")
    return r0


# ── 단계 ──────────────────────────────────────────────────────────────────
def prepare_s0(ids: dict, cfg: dict, env: dict, tmp: Path, generate: bool) -> dict:
    """K3: source=probe_reuse → s0_import(LLM 0), source=new → make_s0(유료, generate=True 일 때만). 요약 JSON 반환."""
    ids_file = tmp / f"s0_ids_{'gen' if generate else 'imp'}.json"; ids_file.write_text(json.dumps(ids), encoding="utf-8")
    summ = tmp / f"s0_summary_{'gen' if generate else 'imp'}.json"
    cmd = [sys.executable, "-X", "utf8", "-m", "benchmark.s0_import", "--probe", str(ROOT / "evidence" / "week2" / "pool_probe_bcb_A.json"), "--ids", str(ids_file),
           "--run-id", cfg["run_ids"]["explore"], "--summary", str(summ)] + (["--generate"] if generate else [])
    rc = subprocess.run(cmd, cwd=str(ROOT), env=env).returncode
    if rc != 0:
        raise SystemExit(f"[pilot] s0 준비 종료 코드 {rc}")
    return json.loads(summ.read_text(encoding="utf-8"))


def round0(ids: list, n: int, env: dict, tmp: Path, arms_root: Path, run_id: str, cfg: dict) -> dict:
    """0회차: B-expert 1회 × n 과제, b_cont=1.0 (→ max_tokens 상한 4096 에 걸림, 실질 무상한). 결과 파일이 있으면 재측정하지 않는다."""
    p = arms_root / run_id / "round0_bcont.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    ids_file = tmp / "round0_ids.json"; ids_file.write_text(json.dumps({"ids": ids[:n]}), encoding="utf-8")
    out = run_arms(ids_file, tmp / "arms_round0.json", env, 1, cfg["round0"]["arm"], 1.0, 1.0)
    costs = [r["cost_usd"] for r in out["rows"] if r["arm"] == cfg["round0"]["arm"]]
    s0c = list(out["shared_s0_cost"].values())
    if any(c is None for c in costs) or any(v is None for v in s0c):
        raise RuntimeError("[pilot] 0회차에 미측정 비용 — b_cont 를 정할 수 없다")
    r0 = {"b_cont": float(np.median(costs)), "a_call_median": float(np.median(s0c)), "n": len(costs), "arm": cfg["round0"]["arm"], "costs": costs,
          "s0_costs": s0c, "round0_arm_usd": round(sum(costs), 8), "max_tokens": [r["max_tokens"] for r in out["rows"]], "stopped_reason": out.get("stopped_reason")}
    p.write_text(json.dumps(r0, ensure_ascii=False, indent=1), encoding="utf-8")
    return r0


def tune_policy(rows, feats, Y, menu: dict, fcfg: dict, seed: int, workers: int = 1, n_perm: int = 0, n_boot: int = 0) -> dict:
    """탐색 절차 = gap_analysis.explore_fit 그대로 (시뮬레이터 pilot_power_v4.fit_policy 와 같은 함수, L3)."""
    return G.explore_fit(rows, feats, Y, menu, fcfg, seed, workers=workers, n_perm=n_perm, n_boot=n_boot)


def explore_stage(args, cfg: dict, ids: dict, env: dict, tmp: Path, arms_root: Path, out_prefix: Path) -> dict:
    t0 = time.time()
    run_id = cfg["run_ids"]["explore"]
    s0_imp = prepare_s0(ids, cfg, env, tmp, generate=False)          # probe_reuse 가져오기 (무료) → 게이트가 완료를 검사
    checks = gate_common(args, cfg, ids, arms_root, "explore")
    s0_gen = prepare_s0(ids, cfg, env, tmp, generate=True)            # new 생성 (유료) — 게이트 뒤
    round0(ids["ids"], cfg["round0"]["n_tasks"], env, tmp, arms_root, run_id, cfg)
    r0 = gate_round0(arms_root / run_id / "round0_bcont.json")
    ids_file = tmp / "explore_ids.json"; ids_file.write_text(json.dumps({"ids": ids["ids"]}), encoding="utf-8")
    flip_file = tmp / "flip_ids.json"; flip_file.write_text(json.dumps({"ids": ids["flip_subset_ids"]}), encoding="utf-8")
    main_out = run_arms(ids_file, tmp / "arms_main.json", env, 1, ",".join(G.ARMS), r0["b_cont"], r0["a_call_median"])
    flip_out = run_arms(flip_file, tmp / "arms_flip.json", env, cfg["sets"]["explore"]["flip_k"], ",".join(cfg["sets"]["explore"]["flip_arms"]), r0["b_cont"], r0["a_call_median"])
    rows = rows_with_features(main_out)
    Y, C, feats, tasks = G.policy_tensor(rows)
    rates = Y.mean(axis=0)
    best = int(np.argmax(rates))
    gate = {"best_arm": G.ARMS[best], "best_rate": float(rates[best]), "threshold": cfg["pool"]["gate"]["threshold"],
            "decision": "진행" if rates[best] <= cfg["pool"]["gate"]["threshold"] else "보류", "basis": cfg["pool"]["gate"]["basis"]}
    # 탐색에서만 (K5): nested CV — 겹 안에서 메뉴(≤ max_selected) 특징 선택, λ 는 메뉴에서 CV 로; P2-pre 는 자기 메뉴에서 따로 선택 (post 것을 물려받지 않음)
    fcfg = cfg["features"]

    def tune(menu):                                     # L3: 실행기·시뮬레이터 공통 함수 (gap_analysis.explore_fit); 여기서만 진단 순열·CI 를 덧붙인다
        fit = tune_policy(rows, feats, Y, menu, fcfg, cfg["sets"]["seed"], args.workers, args.n_perm, args.n_boot)
        cv = {k: {"gain": r["gain"], "ci95": r.get("ci95"), "diag_perm_p": r["p_value"], "pick_dist": r["pick_dist"], "nested": r["nested_selection"]} for k, r in fit["cv"].items()}
        return cv, fit["lambda"], fit["subset"], fit["model"]
    cv, lam_star, subset, model_post = tune(FEATURE_SPECS["post"])
    cv_pre, lam_pre, pre_spec, model_pre = tune(FEATURE_SPECS["pre"])            # P2-pre: 자기 메뉴·자기 튜닝 (K5)
    r_pre = cv_pre[str(lam_pre)]
    r_p1 = G.policy_gain(rows, "P1", n_perm=args.n_perm, n_boot=0, seed=cfg["sets"]["seed"], spec=subset, workers=args.workers, K=fcfg["cv"]["K"], R=fcfg["cv"]["R"], with_ci=False)
    frozen = {"version": "v4", "config_sha256": checks["config_sha256"], "features_version": FEATURES_VERSION, "feature_subset": subset, "pre_subset": pre_spec,
              "lambda": lam_star, "lambda_pre": lam_pre, "p2_post": model_post, "p2_pre": model_pre, "p1": G.fit_p1(feats, Y, best),
              "a_hat": G.ARMS[best], "a_hat_idx": best, "b_cont": r0["b_cont"], "a_call_median": r0["a_call_median"], "seed": cfg["sets"]["seed"],
              "n_explore": len(tasks), "explore_ids": tasks, "pool_gate": gate}
    fz = arms_root / run_id / "frozen_policy.json"
    fz.write_text(json.dumps(frozen, ensure_ascii=False, indent=1), encoding="utf-8")
    fz_sha = hashlib.sha256(fz.read_bytes()).hexdigest()
    fz.with_suffix(".sha256").write_text(fz_sha, encoding="utf-8")
    spend = spend_report(env, [main_out, flip_out], r0["round0_arm_usd"])
    report = {"stage": "explore", "mode": args.backend, "run_id": run_id, "effective_env": effective_env(env), "n_tasks": len(tasks), "pool_gate": gate,
              "round0": {k: r0[k] for k in ("b_cont", "a_call_median", "n", "arm")}, "s0": {"imported": s0_imp["imported"], "generated": s0_gen["generated"]},
              "arms": main_out["summary"], "flip": flip_rates(flip_out),
              "explore_cv": {"lambda_menu": cv, "lambda_star": lam_star, "feature_subset": subset, "n_features": len(subset["num"]) + len(subset["cat"]),
                             "P2_post_gain": cv[str(lam_star)]["gain"], "P2_post_ci95": cv[str(lam_star)]["ci95"],
                             "pre": {"lambda_menu": cv_pre, "lambda_star": lam_pre, "feature_subset": pre_spec, "n_features": len(pre_spec["num"]) + len(pre_spec["cat"])},
                             "P2_pre_gain": r_pre["gain"], "P1_gain": r_p1["gain"], "selection": "nested (겹 안 선택, 사전 등록)",
                             "note": "모델 선택용 CV — 판정 아님. pre/post = 각자 튜닝된 두 정책의 절제 실험"},
              "diag_perm_p": {"P2_post": cv[str(lam_star)]["diag_perm_p"], "P2_pre": r_pre["diag_perm_p"], "P1": r_p1["p_value"], "note": "진단 — 귀무 '특징 ⟂ 결과' ≠ '정책 이득 ≤ 0'"},
              "frozen": {"path": str(fz), "sha256": fz_sha, "a_hat": G.ARMS[best], "lambda": lam_star, "lambda_pre": lam_pre, "commit_hash": "(동결 커밋 뒤 PREREG 에 기입)"},
              "cost": spend, "stopped_reason": main_out.get("stopped_reason") or flip_out.get("stopped_reason"), "elapsed_s": round(time.time() - t0)}
    assert list(report) == cfg["report_items"]["explore"], (list(report), cfg["report_items"]["explore"])
    write_report(report, out_prefix.with_name(out_prefix.name + "_explore"))
    return report


def confirm_stage(args, cfg: dict, ids: dict, confirm_ids: list, env: dict, tmp: Path, arms_root: Path, out_prefix: Path, prior_usd: float) -> dict:
    t0 = time.time()
    run_id = cfg["run_ids"]["confirm"]
    checks = gate_common(args, cfg, ids, arms_root, "confirm")
    if set(confirm_ids) & set(ids["ids"]):
        raise Gate("확인 ∩ 탐색 ≠ ∅")
    fz = json.loads((arms_root / cfg["run_ids"]["explore"] / "frozen_policy.json").read_text(encoding="utf-8"))
    ids_file = tmp / "confirm_ids.json"; ids_file.write_text(json.dumps({"ids": confirm_ids}), encoding="utf-8")
    out = run_arms(ids_file, tmp / "arms_confirm.json", env, 1, ",".join(G.ARMS), fz["b_cont"], fz["a_call_median"])
    rows = rows_with_features(out)
    Y, C, feats, tasks = G.policy_tensor(rows)
    a_hat = int(fz["a_hat_idx"])
    pick = G.apply_p2(fz["p2_post"], feats)                     # 학습 없음 — 동결 계수 적용만
    primary = G.confirm_test(Y, pick, a_hat, n_boot=cfg["features"]["n_boot_explore"], seed=fz["seed"], alpha=cfg["confirm_rule"]["alpha"],
                             threshold=cfg["confirm_rule"]["threshold_pp"] / 100)
    pick_pre, pick_p1 = G.apply_p2(fz["p2_pre"], feats), G.apply_p1(fz["p1"], feats)
    yp, ypre, yp1 = Y[np.arange(len(Y)), pick], Y[np.arange(len(Y)), pick_pre], Y[np.arange(len(Y)), pick_p1]
    post_vs_pre = {"mean_diff": float((yp - ypre).mean()), "b": int(((yp == 1) & (ypre == 0)).sum()), "c": int(((yp == 0) & (ypre == 1)).sum())}
    post_vs_pre["p_mcnemar_onesided"] = G.mcnemar_exact_onesided(post_vs_pre["b"], post_vs_pre["c"])
    secondary = {"P2_post_vs_P2_pre": post_vs_pre, "P2_pre_vs_a_hat": G.confirm_test(Y, pick_pre, a_hat, n_boot=0), "P1_vs_a_hat": G.confirm_test(Y, pick_p1, a_hat, n_boot=0),
                 "oracle_descriptive": {"oracle_minus_fixed_insample": float(Y.max(axis=1).mean() - Y.mean(axis=0).max()), "note": "1회 실행 최대의 표본 내 통계 — 상한 아님 (J6)"}}
    pick_dist = {G.ARMS[a]: float((pick == a).mean()) for a in range(len(G.ARMS))}
    policy_cost = deploy_cost(rows, tasks, C, pick, a_hat)
    spend = spend_report(env, [out], 0.0, prior_usd)
    report = {"stage": "confirm", "mode": args.backend, "run_id": run_id, "effective_env": effective_env(env), "n_tasks": len(tasks), "frozen_hash": checks["frozen_policy"], "primary": primary,
              "secondary": secondary, "arms": out["summary"], "pick_dist": pick_dist, "policy_cost": policy_cost, "cost": spend,
              "stopped_reason": out.get("stopped_reason"), "elapsed_s": round(time.time() - t0)}
    assert list(report) == cfg["report_items"]["confirm"], (list(report), cfg["report_items"]["confirm"])
    write_report(report, out_prefix.with_name(out_prefix.name + "_confirm"))
    return report


def deploy_cost(rows, tasks, C, pick, a_hat) -> dict:
    """세 비용 관점 (K5 → L4): (1) 실험 총지출 = cost(원장). (2) arm 자체 비용 = 선택 arm 의 호출 비용만. (3) 정책 배포 비용 = 선택 arm 비용 + s0 취득 비용 —
    post 정책은 상태를 생성·검증한 **뒤** 고르므로 선택 arm 이 B-solo 여도 s0 비용을 이미 지불했다(제외하지 않는다, L4).
    고정 전략 배포 비용은 별도 관점: 고정 B-solo 는 처음부터 B-solo 만 실행하므로 s0 없이 자기 호출만; 다른 고정 arm 은 s0 + arm.
    가시 검증 $ 는 0 (로컬 docker) — wall_ms 로 따로 보고. None 은 미측정 (nanmean 금지)."""
    ti = {t: i for i, t in enumerate(tasks)}
    s0 = np.full(len(tasks), np.nan); wall = np.zeros(len(tasks))
    for r in rows:
        s0[ti[r["task_id"]]] = np.nan if r["s0_cost_usd"] is None else float(r["s0_cost_usd"]); wall[ti[r["task_id"]]] = r["s0_verify_wall_ms"]
    bsolo = G.ARMS.index("B-solo")
    n = len(tasks)
    state_fix = np.zeros(n) if a_hat == bsolo else s0
    cp, cf = C[np.arange(n), pick], C[:, a_hat]
    m = lambda x: None if np.isnan(x).any() else float(np.mean(x))
    return {"policy_usd_per_task": m(cp), "fixed_usd_per_task": m(cf), "state_acquisition_usd_per_task": m(s0),
            "policy_deploy_usd_per_task": m(cp + s0), "fixed_deploy_usd_per_task": m(cf + state_fix),
            "fixed_arm": G.ARMS[a_hat], "fixed_deploy_includes_s0": bool(a_hat != bsolo),
            "visible_verify_wall_ms_per_task": float(wall.mean()), "n_unpriced": int(np.isnan(C).sum()) + int(np.isnan(s0).sum()),
            "note": "policy_deploy = 선택 arm + s0 (post 정책은 B-solo 를 골라도 s0 를 이미 지불); fixed_deploy = 고정 arm + s0 (고정 B-solo 만 자기 호출); "
                    "실험 총지출은 cost(원장); 가시 검증은 wall_ms"}


def flip_rates(flip_out: dict):
    by = {}
    for r in flip_out["rows"]:
        by.setdefault((r["task_id"], r["arm"]), {})[r["rep"]] = r["hidden_pass"]
    out = {}
    for arm in sorted({a for _, a in by}):
        cells = [v for (t, a), v in by.items() if a == arm and 1 in v and 2 in v]
        out[arm] = {"n_cells": len(cells), "flip_rate": (sum(v[1] != v[2] for v in cells) / len(cells)) if cells else None}
    return out


def write_report(report: dict, prefix: Path) -> None:
    prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 파일럿 보고 — {report['stage']} ({report['mode']}, run_id={report['run_id']}, N={report['n_tasks']}, {report['elapsed_s']}s)", "",
          f"- 실효 설정(env, 단일 출처 = pilot_config_v4.json): {json.dumps(report['effective_env'], ensure_ascii=False)}"]
    if report["stage"] == "explore":
        g, e = report["pool_gate"], report["explore_cv"]
        md += [f"- 풀 관문: 최고 arm {g['best_arm']} {100 * g['best_rate']:.1f}% (문턱 {100 * g['threshold']:.0f}%) → **{g['decision']}**",
               f"- 0회차: b_cont ${report['round0']['b_cont']:.4f}, a_call_median ${report['round0']['a_call_median']:.4f} (n={report['round0']['n']})",
               f"- 탐색 CV(모델 선택용): λ*={e['lambda_star']}, 특징 {e['n_features']}열, P2-post {100 * e['P2_post_gain']:+.1f}pp CI {e['P2_post_ci95']}, "
               f"P2-pre {100 * e['P2_pre_gain']:+.1f}pp, P1 {100 * e['P1_gain']:+.1f}pp; 순열 p(진단) {report['diag_perm_p']['P2_post']:.3f}",
               f"- 동결: â={report['frozen']['a_hat']}, sha256 {report['frozen']['sha256'][:12]}, 커밋 해시 {report['frozen']['commit_hash']}",
               f"- 뒤집힘: {json.dumps(report['flip'], ensure_ascii=False)}"]
    else:
        p = report["primary"]
        md += [f"## 판정: **{p['verdict']}** — 평균 d = {100 * p['mean_d']:+.1f}pp (b={p['b_policy_only']}, c={p['c_fixed_only']}, McNemar 단측 p={p['p_mcnemar_onesided']:.4f}, "
               f"CI95 {[round(100 * x, 1) for x in p['ci95']]}); {p['rule']}",
               f"- 부차: post−pre {100 * report['secondary']['P2_post_vs_P2_pre']['mean_diff']:+.1f}pp (p {report['secondary']['P2_post_vs_P2_pre']['p_mcnemar_onesided']:.3f}); "
               f"P2-pre vs â {100 * report['secondary']['P2_pre_vs_a_hat']['mean_d']:+.1f}pp; P1 vs â {100 * report['secondary']['P1_vs_a_hat']['mean_d']:+.1f}pp; "
               f"oracle(기술) {100 * report['secondary']['oracle_descriptive']['oracle_minus_fixed_insample']:.1f}pp",
               "- 정책 선택 분포: " + ", ".join(f"{k} {100 * v:.0f}%" for k, v in report["pick_dist"].items())
               + f"; arm 만: 정책 ${report['policy_cost']['policy_usd_per_task']} / 고정 ${report['policy_cost']['fixed_usd_per_task']}; "
               f"배포(정책 = arm + s0 ${report['policy_cost']['state_acquisition_usd_per_task']}): 정책 ${report['policy_cost']['policy_deploy_usd_per_task']} / "
               f"고정 {report['policy_cost']['fixed_arm']} ${report['policy_cost']['fixed_deploy_usd_per_task']}"
               f"{'(+s0)' if report['policy_cost']['fixed_deploy_includes_s0'] else '(자기 호출만)'} (과제당)"]
    a = report["arms"]
    md += ["", "| arm | 히든 성공률 | 거부율 | arm 단독 $ | 호출 수 평균 |", "|---|---|---|---|---|"]
    for arm in G.ARMS:
        if arm in a:
            md.append(f"| {arm} | {100 * a[arm]['hidden_pass']:.1f}% | {100 * a[arm]['refused_rate']:.0f}% | ${a[arm]['cost_own_cost_usd']} | {a[arm]['n_calls_mean']:.1f} |")
    s = report["cost"]
    md += ["", f"- 총지출(원장 {s['ledger']['n_calls']} 호출): ${s['total_spent_usd']} = 앞 단계 ${s['prior_stage_usd']} + 0회차 ${s['round0_usd']} + arm ${s['arms_own_usd']} "
           f"+ 여기서 만든 s0 ${s['s0_built_here_usd']} + 미완료 arm ${s['incomplete_usd']} ({s['n_incomplete_arms']}건) (가져온 s0 원 생성비, 역사적 ${s['s0_imported_historical_usd']}; "
           f"미측정 {s['n_unpriced']}; arm 실측 ${s['arms_measured_usd']} / 불명 귀속 ${s['arms_unknown_reserved_usd']}; 검산 {s['check']})",
           f"- 중단 사유: {report['stopped_reason']}"]
    prefix.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=["mock-scenario", "anthropic"])
    ap.add_argument("--stage", required=True, choices=["s0", "explore", "confirm", "all"], help="s0 = 탐색 s0 준비만 (probe_reuse 가져오기 + new 생성), K3")
    ap.add_argument("--out", required=True, help="출력 접두 (…_explore.json / …_confirm.json)")
    ap.add_argument("--n-perm", type=int, default=None, help="기본 = 설정 파일 n_perm_diag")
    ap.add_argument("--n-boot", type=int, default=None, help="기본 = 설정 파일 n_boot_explore")
    ap.add_argument("--workers", type=int, default=14)
    args = ap.parse_args()
    if args.backend == "anthropic" and args.stage == "all":
        raise Gate("실제 백엔드에서 --stage all 금지: 탐색 → (동결 커밋, APPROVAL.json 갱신) → 확인은 별도 호출 (K1)")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    args.n_perm = cfg["features"]["n_perm_diag"] if args.n_perm is None else args.n_perm
    args.n_boot = cfg["features"]["n_boot_explore"] if args.n_boot is None else args.n_boot
    tmp = Path(tempfile.mkdtemp(prefix="pilot_"))
    extra = {}
    if args.backend == "mock-scenario":
        from benchmark.mock_scenario import write_bcb_scenario
        sc = tmp / "scenario.json"; write_bcb_scenario(DRY_IDS, DRY_SCRIPTS, sc, tokens={"prompt": 400, "completion": 500})
        ids = {"ids": DRY_IDS[:4], "probe_reuse_ids": [], "sources": {t: "new" for t in DRY_IDS[:4]}, "flip_subset_n": 2, "flip_subset_ids": DRY_IDS[:2]}
        confirm_ids = DRY_IDS[4:]
        extra = {"HARMONET_MOCK_SCENARIO": str(sc), "HARMONET_MODEL_BUILDER": "claude-haiku-4-5", "HARMONET_MODEL_REVIEWER": "claude-sonnet-4-6",
                 "HARMONET_BUDGET_ROOT": str(tmp / "budget"), "HARMONET_ARMS_ROOT": str(tmp / "arms"), "HARMONET_TRACE_DIR": str(tmp / "traces")}
        cfg = {**cfg, "round0": {**cfg["round0"], "n_tasks": 2}}      # dry-run 규모만 축소 — 규칙은 동일
    else:
        ids = json.loads((ROOT / "evidence" / "week2" / cfg["sets"]["explore"]["file"]).read_text(encoding="utf-8"))
        confirm_ids = json.loads((ROOT / "evidence" / "week2" / cfg["sets"]["confirm"]["file"]).read_text(encoding="utf-8"))["ids"]
        if len(ids["ids"]) != cfg["sets"]["explore"]["n"] or len(confirm_ids) != cfg["sets"]["confirm"]["n"]:
            raise Gate(f"ID 파일 크기가 설정과 다르다: 탐색 {len(ids['ids'])} vs {cfg['sets']['explore']['n']}, 확인 {len(confirm_ids)} vs {cfg['sets']['confirm']['n']}")
    if args.stage == "s0":                                   # K3: 실제 탐색 ID 파일로 s0 준비만 (mock 이면 new 는 시나리오 mock 으로 생성)
        ids = json.loads((ROOT / "evidence" / "week2" / cfg["sets"]["explore"]["file"]).read_text(encoding="utf-8"))
        if args.backend == "mock-scenario":
            from benchmark.mock_scenario import write_bcb_scenario
            new = [t for t in ids["ids"] if ids["sources"][t] == "new"]
            sc = tmp / "scenario_s0.json"; write_bcb_scenario(new, {t: {"s0": "correct"} for t in new}, sc, tokens={"prompt": 400, "completion": 500})
            extra["HARMONET_MOCK_SCENARIO"] = str(sc)
        arms_root = Path(extra.get("HARMONET_ARMS_ROOT", ROOT / "evidence" / "week2"))
        env = _env(args.backend, cfg["run_ids"]["explore"], cfg, extra)
        imp = prepare_s0(ids, cfg, env, tmp, generate=False)
        gate_common(args, cfg, ids, arms_root, "explore")
        gen = prepare_s0(ids, cfg, env, tmp, generate=True)
        rep = {"stage": "s0", "mode": args.backend, "imported": imp["imported"], "generated": gen["generated"], "failed": imp["failed"] + gen["failed"],
               "n_imported": len(imp["imported"]), "n_generated": len(gen["generated"]), "sources": {"probe_reuse": ids["probe_reuse_n"], "new": ids["new_s0_n"]}}
        Path(args.out).with_name(Path(args.out).name + "_s0.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[pilot] s0 준비: 가져오기 {rep['n_imported']} / 생성 {rep['n_generated']} / 실패 {len(rep['failed'])}")
        return 0
    arms_root = Path(extra.get("HARMONET_ARMS_ROOT", ROOT / "evidence" / "week2"))
    out_prefix = Path(args.out)
    env_e, env_c = _env(args.backend, cfg["run_ids"]["explore"], cfg, extra), _env(args.backend, cfg["run_ids"]["confirm"], cfg, extra)
    prior = 0.0
    if args.stage in ("explore", "all"):
        prior = explore_stage(args, cfg, ids, env_e, tmp, arms_root, out_prefix)["cost"]["total_spent_usd"]
    if args.stage in ("confirm", "all"):
        if args.stage == "confirm":
            prior = json.loads(out_prefix.with_name(out_prefix.name + "_explore.json").read_text(encoding="utf-8"))["cost"]["total_spent_usd"]
        confirm_stage(args, cfg, ids, confirm_ids, env_c, tmp, arms_root, out_prefix, prior)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
