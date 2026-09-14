"""
scripts/gap_floor.py — 추정 대상 재정의: 독립 바닥 위의 초과분 (Week2-G). 유료 호출 0.

추정 대상 = oracle − 최선 고정 − **독립 바닥**.  바닥 = 가산 귀무(logit p_ia = τ_i + α_a, 과제×arm 상호작용 없음)에 **관측된 반복 구조(ρ̂)** 를 넣고
생성한 데이터에서 표본 내 oracle gap 의 기대값. 결정적 반복에서는 (과제, arm) 의 독립 실현 자체가 "어느 arm 이 그 과제를 푼다" 를 만들지만 그건
재현 가능한 운이지 일반화 정책이 먹을 수 있는 구조가 아니다 — 그래서 뺀다.

(iii) v2 (G2):
  1. 반복 구조: arm 별 ρ̂_a. 셀(과제, arm)의 k 반복 중 서로 다른 쌍 비율 D_ia = 2s(k−s)/(k(k−1)). 생성 모형(반복 = 확률 ρ 로 잠재 결과, 아니면 새 Bern(p))에서
     E[D] = 2p(1−p)(1−ρ²) 이므로 ρ̂_a² = 1 − mean_i D_ia / mean_i 2p̂_ia(1−p̂_ia) (0~1 로 자름). T 는 정의상 ρ=1 (같은 산출물).
  2. 가산 적합: logit p_ia = τ_i + α_a. 셀 평균을 관측 1개(가중 1)로, IRLS 12회, 과제 효과 τ 에 ridge λ=1.0 (N 작을 때 과적합 방지), α 는 1e-6.
     적합 방식 고정·기록.
  3. 귀무 시뮬레이션 B=2000: 셀마다 잠재 y ~ Bern(p̂), 반복 r 은 확률 ρ̂_a 로 y, 아니면 새 Bern(p̂) (ρ̂≈1 이면 사실상 1개를 k 번 복제, 중간이면
     과분산 반복). T 는 k 번 복제. 표본 내 oracle gap 의 귀무 분포.
  4. 통계량: 관측 표본 내 oracle gap G. p = P(G_null ≥ G). 편향 보정 gap(초과분) = G − mean(G_null) (= 독립 바닥).
     CI: 과제 부트스트랩 외부 1000 × 내부(귀무 기대 재계산) 200.
규칙 R1' = "p < 0.05 ∧ 초과분 ≥ 10pp".

    python -X utf8 scripts/gap_floor.py rows.json               # 실제 데이터 분석
    python -X utf8 scripts/gap_floor.py --g1 | --g2 | --g3      # 합성 검증 (G1 자명 통과, G2 편향·크기, G3 검정력·N)
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")     # 워커 프로세스 × BLAS 스레드 과다 → 156×156 solve 가 2.5s 걸리는 것을 막는다 (G2 에서 확인)

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gap_analysis as G   # noqa: E402
import gap_power as P      # noqa: E402

ARMS = G.ARMS
LAMBDA_TAU = 1.0
IRLS_ITERS = 12
B_NULL = 2000
CI_OUTER, CI_INNER = 1000, 200


# ── (iii) v2 ─────────────────────────────────────────────────────────────
def fit_additive(M: np.ndarray, lam_tau: float = LAMBDA_TAU, iters: int = IRLS_ITERS) -> np.ndarray:
    """logit p_ia = τ_i + α_a 를 셀 평균 M[n, A] 에 IRLS(ridge on τ)로 적합. 반환 p̂[n, A]."""
    n, A = M.shape
    y = np.clip(M, 0.0, 1.0).ravel()
    X = np.zeros((n * A, n + A))
    rows = np.arange(n * A)
    X[rows, np.repeat(np.arange(n), A)] = 1.0
    X[rows, n + np.tile(np.arange(A), n)] = 1.0
    pen = np.concatenate([np.full(n, lam_tau), np.full(A, 1e-6)])
    beta = np.zeros(n + A)
    for _ in range(iters):
        eta = X @ beta
        mu = 1 / (1 + np.exp(-eta))
        w = np.clip(mu * (1 - mu), 1e-6, None)
        z = eta + (y - mu) / w
        H = X.T @ (X * w[:, None]) + np.diag(pen)
        beta = np.linalg.solve(H, X.T @ (w * z))
    return (1 / (1 + np.exp(-(X @ beta)))).reshape(n, A)


def estimate_rho(S: np.ndarray, P_hat: np.ndarray) -> np.ndarray:
    """arm 별 ρ̂ (T 는 1)."""
    n, A, k = S.shape
    s = S.sum(axis=2)
    D = 2 * s * (k - s) / (k * (k - 1)) if k > 1 else np.zeros((n, A))
    var = 2 * P_hat * (1 - P_hat)
    rho2 = 1 - D.mean(axis=0) / np.maximum(var.mean(axis=0), 1e-9)
    rho = np.sqrt(np.clip(rho2, 0.0, 1.0))
    rho[0] = 1.0
    return rho


def null_gaps(P_hat: np.ndarray, rho: np.ndarray, k: int, B: int, rng) -> np.ndarray:
    """가산 귀무 + 반복 구조에서 표본 내 oracle gap B 개 (벡터화)."""
    n, A = P_hat.shape
    y = (rng.random((B, n, A)) < P_hat[None]).astype(np.float32)
    keep = rng.random((B, n, A, k)) < rho[None, None, :, None]
    fresh = rng.random((B, n, A, k)) < P_hat[None, :, :, None]
    S = np.where(keep, y[..., None], fresh).astype(np.float32)
    S[:, :, 0, :] = y[:, :, 0:1]                                    # T: 복제
    M = S.mean(axis=3)                                             # [B, n, A]
    return M.max(axis=2).mean(axis=1) - M.mean(axis=1).max(axis=1)


def analyze_floor(S: np.ndarray, B: int = B_NULL, seed: int = 0, ci: Tuple[int, int] = (CI_OUTER, CI_INNER), with_ci: bool = True) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    n, A, k = S.shape
    M = S.mean(axis=2)
    obs = float(M.max(axis=1).mean() - M.mean(axis=0).max())
    P_hat = fit_additive(M)
    rho = estimate_rho(S, P_hat)
    null = null_gaps(P_hat, rho, k, B, rng)
    floor = float(null.mean())
    excess = obs - floor
    p = float((null >= obs).mean())
    out = {"n_tasks": n, "k": k, "observed_insample_gap": obs, "floor": floor, "excess": excess, "p_value": p, "rho_hat": rho.tolist(),
           "verdict": "통과" if (p < 0.05 and excess >= 0.10) else "미확인", "rule": "R1' = p<0.05 ∧ 초과분≥10pp", "B_null": B,
           "fit": f"IRLS {IRLS_ITERS}, ridge λ_τ={LAMBDA_TAU}, α 1e-6, 셀 평균 1관측", "crossfit_diagnostic": float(G.crossfit_gap(S)[0])}
    if with_ci:
        outer, inner = ci
        vals = np.empty(outer)
        for b in range(outer):
            idx = rng.integers(0, n, n)
            Sb = S[idx]
            Mb = Sb.mean(axis=2)
            ob = Mb.max(axis=1).mean() - Mb.mean(axis=0).max()
            Pb = fit_additive(Mb)
            rb = estimate_rho(Sb, Pb)
            vals[b] = ob - null_gaps(Pb, rb, k, inner, rng).mean()
        out["ci95"] = [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))]
        out["ci"] = {"outer": outer, "inner": inner}
    return out


# ── 합성: 생성기 (gap_power 의 E1, δ_z 는 인자) ────────────────────────────
def make_S(n: int, seed: int, rho: float, k: int, sigma_gamma: float, scale: float, delta_z: float):
    old = P.DELTA_Z
    P.DELTA_Z = delta_z
    try:
        L = P.latent(n, seed, sigma_gamma, scale)
        S = P.draw_reps(L, rho, k)
        m = P.per_rep_prob(L, rho)
    finally:
        P.DELTA_Z = old
    return S, float(P.oracle_gap_of(m))


def true_floor(n: int, seed: int, rho: float, k: int, delta_z: float, n_mc: int = 200) -> float:
    """참 바닥: 같은 구조(σ_γ=0, 같은 δ_z)에 참 ρ 를 넣어 만든 데이터의 표본 내 oracle gap 기대값 (몬테카를로).
    δ_z(s0 조건부 구조)는 가산 적합의 과제 효과가 흡수하므로 바닥에 포함한다 (G2 확인: σ_γ=0, δ_z=2 에서 초과분 ≈ 0)."""
    vals = []
    for j in range(n_mc):
        S, _ = make_S(n, seed + 100_000 + j, rho, k, 0.0, 0.0, delta_z)
        M = S.mean(axis=2)
        vals.append(M.max(axis=1).mean() - M.mean(axis=0).max())
    return float(np.mean(vals))


def calibrate_excess(n: int, seed: int, rho: float, k: int, target_excess: float, delta_z: float, floor: float, sigma_gamma: float = 0.5):
    """참 oracle gap − 참 바닥 = target 이 되는 배율 s (이분법)."""
    def gap(s):
        return make_S(n, seed, rho, k, sigma_gamma, s, delta_z)[1]
    base = gap(0.0)
    if base - floor >= target_excess:
        return 0.0, base
    lo, hi = 0.0, 8.0
    for _ in range(35):
        mid = (lo + hi) / 2
        if gap(mid) - floor < target_excess:
            lo = mid
        else:
            hi = mid
    s = (lo + hi) / 2
    return s, gap(s)


# ── G1: (i)+R1 자명 통과 ────────────────────────────────────────────────
def g1(seeds: int = 20, n_boot: int = 2000) -> List[Dict[str, Any]]:
    out = []
    for delta_z in (2.0, 0.0):
        for rho in (1.0, 0.9, 0.7):
            for N in (60, 150):
                passes, gaps, floors = 0, [], []
                for s in range(seeds):
                    seed = 1000 * s + 7
                    S, tg = make_S(N, seed, rho, 3, 0.0, 0.0, delta_z)
                    g, lo, hi = P.est_crossfit(S, n_boot, seed)
                    passes += P.rule_r1(g, lo)
                    gaps.append(tg)
                out.append({"delta_z": delta_z, "rho": rho, "N": N, "k": 3, "R1_i_pass": passes, "seeds": seeds, "true_gap_mean": float(np.mean(gaps))})
                print("G1", out[-1], flush=True)
    return out


# ── G2: (iii) v2 검증 σ_γ=0 ─────────────────────────────────────────────
def _g2_cell(args):
    rho, N, delta_z, s = args
    seed = 1000 * s + 7
    S, tg = make_S(N, seed, rho, 3, 0.0, 0.0, delta_z)
    r = analyze_floor(S, B_NULL, seed, with_ci=False)
    return {"rho": rho, "N": N, "delta_z": delta_z, "seed": s, "excess": r["excess"], "p": r["p_value"], "verdict": r["verdict"],
            "rho_hat": r["rho_hat"], "true_gap": tg, "floor": r["floor"], "obs": r["observed_insample_gap"]}


def g2(seeds: int = 20, workers: int = 8) -> List[Dict[str, Any]]:
    jobs = [(rho, N, dz, s) for dz in (0.0, 2.0) for rho in (1.0, 0.9, 0.7) for N in (60, 150) for s in range(seeds)]
    with Pool(workers) as pool:
        res = pool.map(_g2_cell, jobs)
    cells = []
    for dz in (0.0, 2.0):
        for rho in (1.0, 0.9, 0.7):
            for N in (60, 150):
                rs = [r for r in res if r["rho"] == rho and r["N"] == N and r["delta_z"] == dz]
                ex = np.array([r["excess"] for r in rs])
                cells.append({"delta_z": dz, "rho": rho, "N": N, "k": 3, "seeds": seeds, "mean_excess": float(ex.mean()), "sd_excess": float(ex.std(ddof=1)),
                              "pass_R1p": sum(r["verdict"] == "통과" for r in rs), "p_lt_05": sum(r["p"] < 0.05 for r in rs),
                              "rho_hat_mean": np.mean([r["rho_hat"] for r in rs], axis=0).round(3).tolist(),
                              "mean_true_gap": float(np.mean([r["true_gap"] for r in rs])), "mean_floor": float(np.mean([r["floor"] for r in rs]))})
                print("G2", cells[-1], flush=True)
    return cells


# ── G3: (iii) 검정력·N ────────────────────────────────────────────────────
def _g3_cell(args):
    rho, N, k, tgt, delta_z, s = args
    seed = 1000 * s + 7
    floor = true_floor(N, seed, rho, k, delta_z, n_mc=60)
    scale, tg = calibrate_excess(N, seed, rho, k, tgt, delta_z, floor)
    S, tg = make_S(N, seed, rho, k, 0.5, scale, delta_z)
    r = analyze_floor(S, B_NULL, seed, with_ci=False)
    return {"rho": rho, "N": N, "k": k, "target": tgt, "seed": s, "true_excess": tg - floor, "true_gap": tg, "true_floor": floor,
            "excess_hat": r["excess"], "p": r["p_value"], "pass": r["verdict"] == "통과"}


def g3(seeds: int = 20, workers: int = 8, delta_z: float = 2.0) -> List[Dict[str, Any]]:
    targets, rhos, Ns, ks = [0.05, 0.10, 0.15, 0.20], [1.0, 0.9, 0.7], [60, 100, 150, 200, 300], [3, 5]
    jobs = [(rho, N, k, t, delta_z, s) for rho in rhos for N in Ns for k in ks for t in targets for s in range(seeds)]
    t0 = time.time()
    with Pool(workers) as pool:
        res = pool.map(_g3_cell, jobs, chunksize=4)
    cells = []
    for rho in rhos:
        for N in Ns:
            for k in ks:
                for t in targets:
                    rs = [r for r in res if (r["rho"], r["N"], r["k"], r["target"]) == (rho, N, k, t)]
                    cells.append({"rho": rho, "N": N, "k": k, "target": t, "seeds": seeds, "true_excess_mean": float(np.mean([r["true_excess"] for r in rs])),
                                  "excess_hat_mean": float(np.mean([r["excess_hat"] for r in rs])), "pass_R1p": sum(r["pass"] for r in rs),
                                  "p_lt_05": sum(r["p"] < 0.05 for r in rs)})
    print(f"G3 done {len(cells)} cells {time.time() - t0:.0f}s", flush=True)
    return cells


def find_xp(cells, seeds):
    res = {}
    for key in sorted({(c["rho"], c["N"], c["k"]) for c in cells}):
        cs = sorted([c for c in cells if (c["rho"], c["N"], c["k"]) == key], key=lambda c: c["target"])
        x = next((c["true_excess_mean"] for c in cs if c["pass_R1p"] / seeds >= 0.8), None)
        res[f"rho={key[0]},N={key[1]},k={key[2]}"] = round(100 * x, 1) if x is not None else f">{100 * cs[-1]['true_excess_mean']:.1f}"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", nargs="?")
    ap.add_argument("--g1", action="store_true")
    ap.add_argument("--g2", action="store_true")
    ap.add_argument("--g3", action="store_true")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.g1:
        res = g1(args.seeds)
    elif args.g2:
        res = g2(args.seeds, args.workers)
    elif args.g3:
        cells = g3(args.seeds, args.workers)
        res = {"cells": cells, "X_prime": find_xp(cells, args.seeds)}
    else:
        rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
        rows = rows["rows"] if isinstance(rows, dict) else rows
        S, tasks, reps = G.tensor(rows)
        res = analyze_floor(S)
        print(json.dumps(res, ensure_ascii=False, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
