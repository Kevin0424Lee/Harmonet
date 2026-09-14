"""
scripts/policy_gain.py — 합성 생성기 v3(결정 시점 특징 포함) + 정책 이득 검정력 (Week2-H1·H3). 유료 호출 0.

H1 생성기 v3 (E1 구조 유지 + 특징 x_i):
  잠재: u_i ~ N(0,1) 난이도, z_i ~ Bern(sig(α+u_i)) s0 히든 결과 (T = z_i), 과제 유형 c_i ∈ {0,1,2} (유형별 최선 계속 arm: A-self / B-expert / B-solo).
  arm 확률: q_iT = z_i; 계속 arm a: sig(β_a + u_i + δ z_i + Δ·1[a = best(c_i)]); B-solo: sig(β_B + u_i + Δ·1[best(c_i) = B-solo]).  Δ = 1.5 (구조적 상호작용, 항상 존재).
  특징 x_i (§8 신호 형식) 와 신호 강도 s ∈ {0, 0.5, 1}:
    visible ∈ {pass, fail}: P(pass | z) = 0.5 + s·(0.4·z − 0.2)  (s=1: z=1→0.9, z=0→0.3; s=0: 0.5 독립)
    error_kind ∈ {E0,E1,E2}: 확률 s 로 c_i 와 같은 색인, 아니면 균등 무작위
    n_failed ~ Poisson(1 + 2·s·(1−z))     artifact_chars ~ N(300 + 60·s·c_i, 80)     s0_cost ~ N(0.003, 0.001) (결과와 무관, 잡음 특징)
    s=0 이면 x_i 는 결과와 완전히 독립(귀무). 결과의 유형 구조는 s 와 무관하게 있다 — 학습 가능한 건 특징이 유형·z 를 드러내는 만큼이다.
  반복: ρ ∈ {1.0, 0.7}, k=1 (관측 = 잠재 y 를 확률 ρ 로, 아니면 새 Bern(q)).
  참 정책 이득 = mean_i q_{i, π*(x_i)} − max_a mean_i q_ia,  π*(x) = argmax_a E[q_a | x] (베이즈: (u, z, c) 사후를 x 우도로 계산, u 는 몬테카를로 격자).
  잠재 확률로 계산하므로 실현 운이 섞이지 않는다.

    python -X utf8 scripts/policy_gain.py --h2   # s=0 크기·편향 (H2 검증)
    python -X utf8 scripts/policy_gain.py --h3   # 검정력·N 격자 (H3)
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import math
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from scipy.stats import beta as _beta, norm, poisson

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gap_analysis as G  # noqa: E402

ARMS = G.ARMS
ALPHA, DELTA_Z, DELTA_TYPE = 0.5, 2.0, 1.5
BETA = np.array([0.0, 0.0, 0.3, 0.0, 0.8, 1.0])
BEST_OF_TYPE = np.array([1, 4, 5])          # 유형 0→A-self, 1→B-expert, 2→B-solo
ERR = ("E0", "E1", "E2")


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def q_matrix(u: np.ndarray, z: np.ndarray, c: np.ndarray, delta: float = DELTA_TYPE) -> np.ndarray:
    n = len(u)
    q = np.zeros((n, len(ARMS)))
    q[:, 0] = z
    best = BEST_OF_TYPE[c]
    for a in (1, 2, 3, 4):
        q[:, a] = _sig(BETA[a] + u + DELTA_Z * z + delta * (best == a))
    q[:, 5] = _sig(BETA[5] + u + delta * (best == 5))
    return q


def generate(n: int, seed: int, s: float, rho: float, delta: float = DELTA_TYPE):
    rng = np.random.default_rng(seed)
    u = rng.normal(0, 1, n)
    z = (rng.random(n) < _sig(ALPHA + u)).astype(float)
    c = rng.integers(0, 3, n)
    q = q_matrix(u, z, c, delta)
    y = (rng.random((n, len(ARMS))) < q).astype(float); y[:, 0] = z
    keep = rng.random((n, len(ARMS))) < rho
    fresh = (rng.random((n, len(ARMS))) < q).astype(float)
    Y = np.where(keep, y, fresh); Y[:, 0] = z                       # k=1 관측
    # 특징
    vis = np.where(rng.random(n) < 0.5 + s * (0.4 * z - 0.2), "pass", "fail")
    err = np.where(rng.random(n) < s, c, rng.integers(0, 3, n))
    nf = rng.poisson(1 + 2 * s * (1 - z))
    ln = rng.normal(300 + 60 * s * c, 80)
    cost = rng.normal(0.003, 0.001, n)
    feats = [{"visible": str(vis[i]), "error_kind": ERR[int(err[i])], "n_failed": int(nf[i]), "artifact_chars": float(ln[i]), "s0_cost": float(cost[i])}
             for i in range(n)]
    C = np.tile(np.array([0.0, 0.004, 0.012, 0.004, 0.012, 0.006]), (n, 1))   # arm 단가 (power_prelim §4)
    return {"u": u, "z": z, "c": c, "q": q, "Y": Y, "feats": feats, "C": C, "delta": delta}


def rows_from(gen: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for i in range(len(gen["z"])):
        for a, arm in enumerate(ARMS):
            rows.append({"task_id": f"s{i}", "arm": arm, "rep": 1, "hidden_pass": bool(gen["Y"][i, a]), "cost_usd": float(gen["C"][i, a]),
                         "budget_refused": False, "features": gen["feats"][i]})
    return rows


# ── 참 정책 이득 (베이즈 정책) ─────────────────────────────────────────────
_UGRID = np.linspace(-3.5, 3.5, 141)
_UW = norm.pdf(_UGRID); _UW /= _UW.sum()


def _lik(f: Dict[str, Any], s: float, z: int, c: int) -> float:
    pv = 0.5 + s * (0.4 * z - 0.2)
    l = pv if f["visible"] == "pass" else 1 - pv
    e = ERR.index(f["error_kind"])
    l *= (s + (1 - s) / 3) if e == c else (1 - s) / 3
    l *= poisson.pmf(f["n_failed"], 1 + 2 * s * (1 - z))
    l *= norm.pdf(f["artifact_chars"], 300 + 60 * s * c, 80)
    return l


def bayes_policy(feats, s: float, delta: float = DELTA_TYPE) -> np.ndarray:
    """π*(x) = argmax_a E[q_a | x]. (u, z, c) 사후 ∝ φ(u)·P(z|u)·(1/3)·P(x|z,c)."""
    pz1 = _sig(ALPHA + _UGRID)
    Q = {}                                                   # (z, c) → E_u-weighted q rows [len(grid), A]
    for z in (0, 1):
        for c in (0, 1, 2):
            Q[(z, c)] = q_matrix(_UGRID, np.full(len(_UGRID), float(z)), np.full(len(_UGRID), c, dtype=int), delta)
    picks = []
    for f in feats:
        num = np.zeros(len(ARMS)); den = 0.0
        for z in (0, 1):
            wz = _UW * (pz1 if z == 1 else 1 - pz1)
            for c in (0, 1, 2):
                l = _lik(f, s, z, c) / 3
                num += l * (wz[:, None] * Q[(z, c)]).sum(axis=0)
                den += l * wz.sum()
        picks.append(int(np.argmax(num / den)))
    return np.array(picks)


def true_gain(gen: Dict[str, Any], s: float) -> float:
    pick = bayes_policy(gen["feats"], s, gen["delta"])
    q = gen["q"]
    return float(q[np.arange(len(pick)), pick].mean() - q.mean(axis=0).max())


# ── 실험 ────────────────────────────────────────────────────────────────────
def _cell(args):
    s, rho, N, seed_i, learner, n_perm, R, delta = args
    seed = 1000 * seed_i + 11
    gen = generate(N, seed, s, rho, delta)
    tg = true_gain(gen, s)
    r = G.policy_gain(rows_from(gen), learner, n_perm=n_perm, n_boot=0, seed=seed, with_ci=False, R=R)
    return {"s": s, "rho": rho, "N": N, "delta": delta, "seed": seed_i, "learner": learner, "true_gain": tg, "gain": r["gain"], "p": r["p_value"],
            "pass": r["verdict"] == "통과", "cost_policy": r["cost_policy_usd"], "cost_fixed": r["cost_fixed_usd"]}


def clopper_pearson(x: int, n: int):
    lo = 0.0 if x == 0 else float(_beta.ppf(0.025, x, n - x + 1))
    hi = 1.0 if x == n else float(_beta.ppf(0.975, x + 1, n - x))
    return lo, hi


def fmt_rate(x, n):
    lo, hi = clopper_pearson(x, n)
    return f"{x}/{n} [{100 * lo:.0f},{100 * hi:.0f}]"


def summarize(res, keys):
    cells = []
    for key in sorted({tuple(r[k] for k in keys) for r in res}):
        rs = [r for r in res if tuple(r[k] for k in keys) == key]
        cells.append({**dict(zip(keys, key)), "seeds": len(rs), "true_gain_mean": float(np.mean([r["true_gain"] for r in rs])),
                      "gain_mean": float(np.mean([r["gain"] for r in rs])), "bias": float(np.mean([r["gain"] - r["true_gain"] for r in rs])),
                      "pass": sum(r["pass"] for r in rs), "p_lt_05": sum(r["p"] < 0.05 for r in rs),
                      "cost_policy": float(np.mean([r["cost_policy"] for r in rs])), "cost_fixed": float(np.mean([r["cost_fixed"] for r in rs]))})
    return cells


def run(ss, rhos, Ns, seeds, learners, n_perm, R, workers, deltas=(DELTA_TYPE,)):
    jobs = [(s, rho, N, i, L, n_perm, R, d) for d in deltas for s in ss for rho in rhos for N in Ns for L in learners for i in range(seeds)]
    t0 = time.time()
    with Pool(workers) as pool:
        res = pool.map(_cell, jobs, chunksize=2)
    print(f"{len(jobs)} jobs {time.time() - t0:.0f}s", flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h2", action="store_true")
    ap.add_argument("--h3", action="store_true")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--n-perm", type=int, default=500)
    ap.add_argument("--R", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.h2:
        res = run([0.0], [1.0, 0.7], [100, 150, 200, 300], args.seeds, ["P1", "P2"], args.n_perm, args.R, args.workers)
        out = {"config": {"n_perm": args.n_perm, "R": args.R, "seeds": args.seeds, "s": [0.0]}, "cells": summarize(res, ["learner", "rho", "N"]), "raw": res}
    else:
        # Δ 축 추가: s 만으로는 참 정책 이득이 Δ=1.5 에서 ≤ 6.6pp 라 10pp 문턱 위를 볼 수 없다 → Δ ∈ {1.5, 3.0} (3.0 에서 s=1 이득 ≈ 11pp)
        res = run([0.0, 0.5, 1.0], [1.0, 0.7], [100, 150, 200, 300], args.seeds, ["P1", "P2"], args.n_perm, args.R, args.workers, deltas=(1.5, 3.0))
        cells = summarize(res, ["learner", "delta", "rho", "N", "s"])
        out = {"config": {"n_perm": args.n_perm, "R": args.R, "seeds": args.seeds}, "cells": cells, "raw": res}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in out["cells"]:
        print(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
