"""
scripts/pilot_power_v4.py — 설계 v4(2단계 동결)의 검정력·귀무 크기·편향 분해, 합성 (Week2-J4). 유료 호출 0.

구조 = 파일럿과 같다: 탐색 100 에서 P2-post 학습(λ = 사전 등록값 1.0) + â = 탐색 최고 arm → 확인 200 에 적용 → d_i = y[i, π̂(i)] − y[i, â] →
정확 McNemar 단측 p < 0.05 ∧ 평균 d ≥ 10pp → 통과 (gap_analysis.confirm_test). 파이프라인 전체(탐색 선택 포함)의 통과율을 센다.
생성기 = policy_gain.generate (H1 v3), k=1 이므로 ρ 축 없음(ρ=1; 뒤집힘은 k=2 부분집합만의 문제). 특징 메뉴 크기 f ∈ {6, 12, 20, 28} = v3 정보 특징 5 + 잡음 (f−5)
(귀무 (b) 는 5 + 난도 대리 1 + 잡음 (f−6)). K4: **실제 탐색 절차 포함** — gap_analysis.select_features(메뉴 → ≤ max_selected), λ 메뉴 CV 선택, 풀 관문(최고 arm ≤ 80%,
초과 → 보류 = 통과 아님), 그다음 P2-post 학습·â. 결과 축은 학습된 정책의 참 이득(π̂ − â, N=5000)의 구간; 베이즈 목표값은 생성 조건 열로만.

귀무 2종: (a) 특징 ⟂ 결과 (s=0, Δ=1.5: 유형 구조는 있으나 특징이 못 봄)  (b) 특징이 난도(u)만 예측·최선 arm 불변 (Δ=0, 난도 대리 u+N(0,0.5), 나머지 s=0).
대립: 참 베이즈 이득 {5, 10, 15pp} — Δ 를 이분법으로 맞춤(v3 기저에서 천장 ≈ 14pp 라 15pp 는 기저 평탄화 BETA_FLAT 변형에서 Δ 를 맞춘다, 명시).
편향 분해(복제마다): 학습된 π̂·â 를 큰 평가 표본 N=5000 에 적용한 참 기대 차이 truth = mean q[i, π̂(i)] − mean q[:, â] 와 확인 200 추정 mean d → bias = 추정 − truth.
손실 2열(K4): 정책 학습 손실 = (베이즈 − 참 최선 고정) − (학습 정책 − 참 최선 고정); 고정 선택 손실 = 참 최선 고정 − 탐색 선택 고정 â. 상수 보정 없음.

    python -X utf8 scripts/pilot_power_v4.py --seeds 20 --workers 14 --out evidence/week2/pilot_power_v4
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gap_analysis as G   # noqa: E402
import policy_gain as PG   # noqa: E402

N_EXPLORE, N_CONFIRM, N_BIG = 100, 200, 5000
LAMBDA = 1.0                                  # 사전 등록값 (features.P2_CONFIG["l2_lambda"])
FEATS = (6, 12, 20, 28)                       # 특징 메뉴 크기 (정보 5 + 잡음); 실제 메뉴 28 열, max_selected 20 은 f=28 에서만 작동
TARGETS = (0.05, 0.10, 0.15)
BETA_FLAT = np.array([0.0, 0.3, 0.3, 0.3, 0.3, 0.3])
NUM5, CAT2 = ["n_failed", "artifact_chars", "s0_cost"], ["visible", "error_kind"]


def _with_beta(beta):
    PG.BETA[:] = beta


def bayes_gain(s: float, delta: float, beta, n: int = 3000, seeds=(1, 2)) -> float:
    _with_beta(beta)
    return float(np.mean([PG.true_gain(PG.generate(n, sd, s, 1.0, delta=delta), s) for sd in seeds]))


def calibrate(target: float, beta, lo: float = 0.2, hi: float = 6.0, iters: int = 12) -> float:
    """참 베이즈 이득(s=1)이 target 이 되는 Δ (이분법, 단조 증가)."""
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if bayes_gain(1.0, mid, beta) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def modes(calib):
    return {"null_a": {"s": 0.0, "delta": PG.DELTA_TYPE, "beta": list(PG.BETA), "difficulty": False},
            "null_b": {"s": 0.0, "delta": 0.0, "beta": list(PG.BETA), "difficulty": True},
            **{f"alt_{int(100 * t)}pp": {"s": 1.0, "delta": calib[t]["delta"], "beta": calib[t]["beta"], "difficulty": False} for t in TARGETS}}


def gen(n: int, seed: int, m: dict, n_feat: int):
    _with_beta(m["beta"])
    g = PG.generate(n, seed, m["s"], 1.0, delta=m["delta"])
    rng = np.random.default_rng(seed + 777)
    n_noise = n_feat - 5 - (1 if m["difficulty"] else 0)
    noise = rng.normal(0, 1, (n, max(0, n_noise)))
    for i, f in enumerate(g["feats"]):
        if m["difficulty"]:
            f["difficulty"] = float(g["u"][i] + rng.normal(0, 0.5))
        for j in range(n_noise):
            f[f"noise_{j}"] = float(noise[i, j])
    return g


def spec_for(m: dict, n_feat: int):
    n_noise = n_feat - 5 - (1 if m["difficulty"] else 0)
    return {"num": NUM5 + (["difficulty"] if m["difficulty"] else []) + [f"noise_{j}" for j in range(n_noise)], "cat": CAT2}


def fit_policy(g_ex: dict, menu: dict, rows_ex, fcfg: dict, seed: int, R: int):
    """탐색 절차 그대로 (K4 = pilot_dryrun.explore_stage 와 같은 규칙): 메뉴에서 특징 선택(≤ max_selected) → λ 메뉴 CV 선택 → P2-post 학습 → â = 탐색 최고 arm.
    반환 (apply, a_hat, lambda*, subset, cv gains)."""
    subset = G.select_features(g_ex["feats"], g_ex["Y"], menu, fcfg["lambda_default"], fcfg["max_selected"])
    cv = {}
    for lam in fcfg["lambda_menu"]:
        cv[lam] = G.policy_gain(rows_ex, "P2", n_perm=0, n_boot=0, seed=seed, spec=subset, with_ci=False, R=R, lam=lam)["gain"]
    lam_star = max(fcfg["lambda_menu"], key=lambda l: cv[l])
    model = G.fit_p2(g_ex["feats"], g_ex["Y"], subset, lam=lam_star)
    a_hat = int(np.argmax(g_ex["Y"].mean(axis=0)))
    return (lambda feats: G.apply_p2(model, feats)), a_hat, lam_star, subset, cv


def _cell(args):
    name, m, n_feat, seed_i, fcfg, R, gate_thr = args
    seed = 10_000 * seed_i + 17
    menu = spec_for(m, n_feat)
    g_ex, g_cf, g_big = gen(N_EXPLORE, seed, m, n_feat), gen(N_CONFIRM, seed + 1, m, n_feat), gen(N_BIG, seed + 2, m, n_feat)
    rates = g_ex["Y"].mean(axis=0)
    gate_hold = bool(rates.max() > gate_thr)                                                       # 풀 관문 (탐색 자료)
    apply, a_hat, lam_star, subset, cv = fit_policy(g_ex, menu, PG.rows_from(g_ex), fcfg, seed, R)
    pick_cf = apply(g_cf["feats"])
    r = G.confirm_test(g_cf["Y"], pick_cf, a_hat, n_boot=500, seed=seed)
    pick_big = apply(g_big["feats"])
    q = g_big["q"]
    fixed_true = float(q.mean(axis=0).max())                                                        # 참 최선 고정 (N=5000)
    pol_true = float(q[np.arange(N_BIG), pick_big].mean())                                           # 학습 정책의 참 기대 성공
    ahat_true = float(q[:, a_hat].mean())                                                            # 탐색이 고른 고정 arm 의 참 기대 성공
    truth = pol_true - ahat_true                                                                     # 학습된 정책의 참 이득 (= 확인 판정의 추정 대상)
    bayes = PG.true_gain(g_big, m["s"]) if not m["difficulty"] else float("nan")                    # 베이즈 − 참 최선 고정 (생성 조건 열)
    loss_policy = (bayes - (pol_true - fixed_true)) if not np.isnan(bayes) else None                # 정책 학습 손실 = (베이즈−참최선) − (학습정책−참최선)
    loss_fixed = fixed_true - ahat_true                                                              # 고정 선택 손실 = 참 최선 고정 − 탐색 선택 고정
    passed = (r["verdict"] == "통과") and not gate_hold
    return {"mode": name, "n_feat": n_feat, "seed": seed_i, "a_hat": G.ARMS[a_hat], "gate_hold": gate_hold, "best_rate_explore": float(rates.max()),
            "lambda_star": lam_star, "n_selected": len(subset["num"]) + len(subset["cat"]), "mean_d": r["mean_d"], "p": r["p_mcnemar_onesided"],
            "pass": passed, "pass_ignoring_gate": r["verdict"] == "통과", "ci95": r["ci95"], "truth": truth, "bias": r["mean_d"] - truth, "bayes": bayes,
            "loss_policy": loss_policy, "loss_fixed": loss_fixed, "pol_minus_best": pol_true - fixed_true,
            "ci_covers_truth": bool(r["ci95"][0] <= truth <= r["ci95"][1]), "pick_share_T": float((pick_cf == 0).mean())}


BINS = ((-1.0, 0.0), (0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 1.0))


def summarize(res):
    cells = []
    for key in sorted({(r["mode"], r["n_feat"]) for r in res}):
        rs = [r for r in res if (r["mode"], r["n_feat"]) == key]
        n = len(rs)
        has_b = key[0] != "null_b"
        cells.append({"mode": key[0], "n_feat": key[1], "seeds": n, "pass": PG.fmt_rate(sum(r["pass"] for r in rs), n),
                      "pass_ignoring_gate": PG.fmt_rate(sum(r["pass_ignoring_gate"] for r in rs), n), "gate_hold": sum(r["gate_hold"] for r in rs), "p_lt_05": sum(r["p"] < 0.05 for r in rs),
                      "mean_d": float(np.mean([r["mean_d"] for r in rs])), "truth": float(np.mean([r["truth"] for r in rs])),
                      "bias": float(np.mean([r["bias"] for r in rs])), "bias_sd": float(np.std([r["bias"] for r in rs], ddof=1)),
                      "bayes": float(np.nanmean([r["bayes"] for r in rs])) if has_b else None,
                      "loss_policy": float(np.mean([r["loss_policy"] for r in rs])) if has_b else None,
                      "loss_fixed": float(np.mean([r["loss_fixed"] for r in rs])), "ci_cover_truth": PG.fmt_rate(sum(r["ci_covers_truth"] for r in rs), n),
                      "lambda_dist": {str(l): sum(r["lambda_star"] == l for r in rs) for l in sorted({r["lambda_star"] for r in rs})},
                      "n_selected_mean": float(np.mean([r["n_selected"] for r in rs])),
                      "a_hat_dist": {a: sum(r["a_hat"] == a for r in rs) for a in sorted({r["a_hat"] for r in rs})}})
    return cells


def by_truth_bin(res):
    """결과 축 = 학습된 정책의 참 이득(truth) 구간 — 생성 조건(베이즈 목표)과 무관하게 모은다."""
    out = []
    for lo, hi in BINS:
        rs = [r for r in res if lo <= r["truth"] < hi]
        n = len(rs)
        label = "< 0pp" if lo < 0 else (f"≥ {100 * lo:.0f}pp" if hi >= 1 else f"[{100 * lo:.0f}, {100 * hi:.0f})pp")
        out.append({"bin": label, "n": n, "pass": PG.fmt_rate(sum(r["pass"] for r in rs), n) if n else "—",
                    "pass_ignoring_gate": PG.fmt_rate(sum(r["pass_ignoring_gate"] for r in rs), n) if n else "—", "gate_hold": sum(r["gate_hold"] for r in rs),
                    "mean_d": float(np.mean([r["mean_d"] for r in rs])) if n else None, "truth": float(np.mean([r["truth"] for r in rs])) if n else None,
                    "bias": float(np.mean([r["bias"] for r in rs])) if n else None})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--null-seeds", type=int, default=60, help="귀무 셀은 더 많이 — '≤ 8%' 를 정확 이항 구간으로 보려면 0/20 [0,17] 로는 부족")
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--out", required=True)
    ap.add_argument("--R", type=int, default=5, help="λ 선택 CV 의 셔플 수 (설정 기본 20 은 느려서 합성에선 5)")
    args = ap.parse_args()
    t0 = time.time()
    calib = {}
    for t in TARGETS:
        beta = list(PG.BETA) if t < 0.145 else list(BETA_FLAT)          # v3 기저 천장 ≈ 14pp → 15pp 는 평탄 기저
        d = calibrate(t, beta)
        calib[t] = {"delta": d, "beta": beta, "bayes_check": bayes_gain(1.0, d, beta)}
        print(f"calibrated {t:.2f}: delta={d:.3f} beta={beta} bayes={calib[t]['bayes_check']:.4f}", flush=True)
    M = modes(calib)
    cfg = json.loads((Path(__file__).resolve().parent.parent / "evidence" / "week2" / "pilot_config_v4.json").read_text(encoding="utf-8"))
    fcfg, gate_thr = cfg["features"], cfg["pool"]["gate"]["threshold"]
    jobs = [(name, m, f, i, fcfg, args.R, gate_thr) for name, m in M.items() for f in FEATS for i in range(args.null_seeds if name.startswith("null") else args.seeds)]
    with Pool(args.workers) as pool:
        res = pool.map(_cell, jobs, chunksize=2)
    cells = summarize(res)
    bins = by_truth_bin(res)
    out = {"config": {"N_explore": N_EXPLORE, "N_confirm": N_CONFIRM, "N_big": N_BIG, "lambda": LAMBDA, "feats": FEATS, "seeds": args.seeds, "null_seeds": args.null_seeds, "rho": 1.0,
                      "calibration": {str(k): v for k, v in calib.items()}, "modes": M, "procedure": "탐색 절차 포함: 특징 메뉴(≤max_selected) 선택 + λ 메뉴 CV 선택 + 풀 관문",
                      "max_selected": fcfg["max_selected"], "lambda_menu": fcfg["lambda_menu"], "gate_threshold": gate_thr, "cv_R": args.R},
           "cells": cells, "by_truth_bin": bins, "raw": res, "elapsed_s": round(time.time() - t0)}
    Path(args.out + ".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 설계 v4 전체 절차 검정력·귀무 크기·편향 분해 (합성, Week2-K4)", "",
          f"탐색 {N_EXPLORE}: 특징 메뉴(정보 5 + 잡음, 메뉴 크기 f) → select_features(≤{fcfg['max_selected']}) → λ ∈ {fcfg['lambda_menu']} CV(K5×R{args.R}) 선택 → P2-post 학습 → "
          f"â = 탐색 최고 arm; 풀 관문 최고 arm ≤ {gate_thr:.0%} (초과 → 보류 = 통과 아님). 확인 {N_CONFIRM}: 대응 McNemar 단측 p<0.05 ∧ 평균 d ≥ 10pp. "
          f"seed {args.seeds} (귀무 {args.null_seeds}), 정확 이항 95% 구간. '통과' = **해당 조건에서 관측된 통과율**. ρ 축 없음(k=1).", "",
          "## 결과 축 = 학습된 정책의 참 이득 (π̂ − â, N=5000) 구간 — 생성 조건과 무관하게 모음", "",
          "| 참 이득 구간 | n | 통과 (관문 포함) | 통과 (관문 무시) | 관문 보류 | 평균 d(200) | 참 이득 평균 | 편향 |", "|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: "" if v is None else f"{100 * v:+.1f}pp"
    for b in bins:
        md.append(f"| {b['bin']} | {b['n']} | {b['pass']} | {b['pass_ignoring_gate']} | {b['gate_hold']} | {fmt(b['mean_d'])} | {fmt(b['truth'])} | {fmt(b['bias'])} |")
    md += ["", "## 생성 조건별 (베이즈 목표값은 조건 열)", "",
           "| 모드 | 메뉴 f | 통과 (관문 포함) | 통과 (관문 무시) | 관문 보류 | p<.05 | 평균 d | 참 이득(π̂−â) | 편향 (sd) | 베이즈−참최선 | 정책 학습 손실 | 고정 선택 손실 | λ* 분포 | 선택 열 수 | â 분포 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        bay = "—" if c["bayes"] is None else f"{100 * c['bayes']:.1f}pp"
        lp = "—" if c["loss_policy"] is None else f"{100 * c['loss_policy']:+.1f}pp"
        md.append(f"| {c['mode']} | {c['n_feat']} | {c['pass']} | {c['pass_ignoring_gate']} | {c['gate_hold']} | {c['p_lt_05']} | {100 * c['mean_d']:+.1f}pp | {100 * c['truth']:+.1f}pp | "
                  f"{100 * c['bias']:+.1f} ({100 * c['bias_sd']:.1f}) | {bay} | {lp} | {100 * c['loss_fixed']:+.1f}pp | {c['lambda_dist']} | {c['n_selected_mean']:.1f} | {c['a_hat_dist']} |")
    md += ["", "손실 분해 (K4 기준선 통일): 정책 학습 손실 = (베이즈 − 참 최선 고정) − (학습 정책 − 참 최선 고정); 고정 선택 손실 = 참 최선 고정 − 탐색 선택 고정 â. "
           "참 이득(π̂ − â) = (베이즈 − 참최선) − 정책 학습 손실 + 고정 선택 손실.",
           "보정: " + "; ".join(f"{k}: Δ={v['delta']:.3f}, BETA={v['beta']}, 베이즈 {100 * v['bayes_check']:.1f}pp" for k, v in calib.items()),
           "귀무 (b) 의 베이즈 열은 '—': v3 우도가 난도 대리를 모른다. 최선 arm 불변은 참 이득 ≈ 0 과 â 분포로 본다.",
           "풀 관문: 합성 생성기(BETA 기저)의 최고 arm 성공률이 ≈ 80% 근처라 대부분의 복제가 '보류' 다 — 이는 생성기 기저의 성질이지 실제 풀(프로브 B-solo 75%)에 대한 진술이 아니다. "
           "그래서 '관문 무시' 열을 같이 둔다: 관문을 지난 뒤의 판정 성질은 그 열로 읽는다.", f"소요 {out['elapsed_s']}s"]
    Path(args.out + ".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
