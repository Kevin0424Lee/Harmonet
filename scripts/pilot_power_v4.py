"""
scripts/pilot_power_v4.py — 설계 v4(2단계 동결)의 검정력·귀무 크기·편향 분해, 합성 (Week2-J4). 유료 호출 0.

구조 = 파일럿과 같다: 탐색 100 에서 P2-post 학습(λ = 사전 등록값 1.0) + â = 탐색 최고 arm → 확인 200 에 적용 → d_i = y[i, π̂(i)] − y[i, â] →
정확 McNemar 단측 p < 0.05 ∧ 평균 d ≥ 10pp → 통과 (gap_analysis.confirm_test). 파이프라인 전체(탐색 선택 포함)의 통과율을 센다.
생성기 = policy_gain.generate (H1 v3), k=1 이므로 ρ 축 없음(ρ=1; 뒤집힘은 k=2 부분집합만의 문제). 특징 수 f ∈ {6, 12, 20} = v3 정보 특징 5 + 잡음 (f−5)
(귀무 (b) 는 5 + 난도 대리 1 + 잡음 (f−6)). 특징 부분집합 선택(탐색 메뉴 28→≤20)은 여기서 흉내내지 않는다 — f 를 고정 축으로 둔다 (명시).

귀무 2종: (a) 특징 ⟂ 결과 (s=0, Δ=1.5: 유형 구조는 있으나 특징이 못 봄)  (b) 특징이 난도(u)만 예측·최선 arm 불변 (Δ=0, 난도 대리 u+N(0,0.5), 나머지 s=0).
대립: 참 베이즈 이득 {5, 10, 15pp} — Δ 를 이분법으로 맞춤(v3 기저에서 천장 ≈ 14pp 라 15pp 는 기저 평탄화 BETA_FLAT 변형에서 Δ 를 맞춘다, 명시).
편향 분해(복제마다): 학습된 π̂·â 를 큰 평가 표본 N=5000 에 적용한 참 기대 차이 truth = mean q[i, π̂(i)] − mean q[:, â] 와 확인 200 추정 mean d → bias = 추정 − truth.
베이즈 최적 대비 손실 = bayes(5000) − truth 별도 열. 상수 보정 없음.

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
FEATS = (6, 12, 20)
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


def fit_policy(g_ex: dict, spec: dict):
    """탐색 자료에서 P2-post(gap_analysis.fit_p2, 파일럿과 같은 코드) + â. 반환: 적용 함수 (feats → pick)."""
    model = G.fit_p2(g_ex["feats"], g_ex["Y"], spec, lam=LAMBDA)
    a_hat = int(np.argmax(g_ex["Y"].mean(axis=0)))
    return (lambda feats: G.apply_p2(model, feats)), a_hat


def _cell(args):
    name, m, n_feat, seed_i = args
    seed = 10_000 * seed_i + 17
    spec = spec_for(m, n_feat)
    g_ex, g_cf, g_big = gen(N_EXPLORE, seed, m, n_feat), gen(N_CONFIRM, seed + 1, m, n_feat), gen(N_BIG, seed + 2, m, n_feat)
    apply, a_hat = fit_policy(g_ex, spec)
    pick_cf = apply(g_cf["feats"])
    r = G.confirm_test(g_cf["Y"], pick_cf, a_hat, n_boot=500, seed=seed)
    pick_big = apply(g_big["feats"])
    truth = float(g_big["q"][np.arange(N_BIG), pick_big].mean() - g_big["q"][:, a_hat].mean())     # 학습된 π̂·â 의 참 기대 차이
    bayes = PG.true_gain(g_big, m["s"]) if not m["difficulty"] else float("nan")                    # (b) 의 v3 우도는 난도 대리를 모름 → 미정의
    return {"mode": name, "n_feat": n_feat, "seed": seed_i, "a_hat": G.ARMS[a_hat], "mean_d": r["mean_d"], "p": r["p_mcnemar_onesided"],
            "pass": r["verdict"] == "통과", "ci95": r["ci95"], "truth": truth, "bias": r["mean_d"] - truth, "bayes": bayes,
            "loss_vs_bayes": (bayes - truth) if not np.isnan(bayes) else None, "ci_covers_truth": bool(r["ci95"][0] <= truth <= r["ci95"][1]),
            "pick_share_T": float((pick_cf == 0).mean())}


def summarize(res):
    cells = []
    for key in sorted({(r["mode"], r["n_feat"]) for r in res}):
        rs = [r for r in res if (r["mode"], r["n_feat"]) == key]
        n = len(rs)
        cells.append({"mode": key[0], "n_feat": key[1], "seeds": n, "pass": PG.fmt_rate(sum(r["pass"] for r in rs), n),
                      "p_lt_05": sum(r["p"] < 0.05 for r in rs), "mean_d": float(np.mean([r["mean_d"] for r in rs])),
                      "truth": float(np.mean([r["truth"] for r in rs])), "bias": float(np.mean([r["bias"] for r in rs])),
                      "bias_sd": float(np.std([r["bias"] for r in rs], ddof=1)),
                      "bayes": float(np.nanmean([r["bayes"] for r in rs])) if key[0] != "null_b" else None,
                      "loss_vs_bayes": float(np.mean([r["loss_vs_bayes"] for r in rs])) if key[0] != "null_b" else None,
                      "ci_cover_truth": PG.fmt_rate(sum(r["ci_covers_truth"] for r in rs), n),
                      "a_hat_dist": {a: sum(r["a_hat"] == a for r in rs) for a in sorted({r["a_hat"] for r in rs})}})
    return cells


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--null-seeds", type=int, default=60, help="귀무 셀은 더 많이 — '≤ 8%' 를 정확 이항 구간으로 보려면 0/20 [0,17] 로는 부족")
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    t0 = time.time()
    calib = {}
    for t in TARGETS:
        beta = list(PG.BETA) if t < 0.145 else list(BETA_FLAT)          # v3 기저 천장 ≈ 14pp → 15pp 는 평탄 기저
        d = calibrate(t, beta)
        calib[t] = {"delta": d, "beta": beta, "bayes_check": bayes_gain(1.0, d, beta)}
        print(f"calibrated {t:.2f}: delta={d:.3f} beta={beta} bayes={calib[t]['bayes_check']:.4f}", flush=True)
    M = modes(calib)
    jobs = [(name, m, f, i) for name, m in M.items() for f in FEATS for i in range(args.null_seeds if name.startswith("null") else args.seeds)]
    with Pool(args.workers) as pool:
        res = pool.map(_cell, jobs, chunksize=2)
    cells = summarize(res)
    out = {"config": {"N_explore": N_EXPLORE, "N_confirm": N_CONFIRM, "N_big": N_BIG, "lambda": LAMBDA, "feats": FEATS, "seeds": args.seeds, "null_seeds": args.null_seeds, "rho": 1.0,
                      "calibration": {str(k): v for k, v in calib.items()}, "modes": M, "note": "특징 부분집합 선택은 흉내내지 않음(f 고정 축)"},
           "cells": cells, "raw": res, "elapsed_s": round(time.time() - t0)}
    Path(args.out + ".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 설계 v4 검정력·귀무 크기·편향 분해 (합성, Week2-J4)", "",
          f"탐색 {N_EXPLORE} 학습(P2-post, λ={LAMBDA}) + â → 확인 {N_CONFIRM} 대응 McNemar 단측 p<0.05 ∧ 평균 d ≥ 10pp. seed {args.seeds} (귀무 {args.null_seeds}), 정확 이항 95% 구간. "
          "'통과' 열은 **해당 조건에서 관측된 통과율**이다 — 한 셀로 '80% at Xpp' 를 쓰지 않는다. 순열 미사용. ρ 축 없음(k=1).", "",
          "| 모드 | f | 통과 | p<.05 | 평균 d(200) | truth(π̂,â @5000) | 편향 = 추정−truth (sd) | 베이즈 | 손실 = 베이즈−truth | CI 포함(truth) | â 분포 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        bay = "—" if c["bayes"] is None else f"{100 * c['bayes']:.1f}pp"
        loss = "—" if c["loss_vs_bayes"] is None else f"{100 * c['loss_vs_bayes']:+.1f}pp"
        md.append(f"| {c['mode']} | {c['n_feat']} | {c['pass']} | {c['p_lt_05']} | {100 * c['mean_d']:+.1f}pp | {100 * c['truth']:+.1f}pp | {100 * c['bias']:+.1f} ({100 * c['bias_sd']:.1f}) | "
                  f"{bay} | {loss} | {c['ci_cover_truth']} | {c['a_hat_dist']} |")
    md += ["", "보정: " + "; ".join(f"{k}: Δ={v['delta']:.3f}, BETA={v['beta']}, 베이즈 {100 * v['bayes_check']:.1f}pp" for k, v in calib.items()),
           "귀무 (b) 의 베이즈 열은 '—': v3 우도가 난도 대리를 모른다. 최선 arm 불변은 truth ≈ 0 과 â 분포로 본다.", f"소요 {out['elapsed_s']}s"]
    Path(args.out + ".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
