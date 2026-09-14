"""
scripts/gap_power.py — 구조적 합성 생성기 + 추정량 3종 + 전체 규칙 검정력 (Week2-F4, 이전 E1~E3 흡수). 유료 호출 0.

F4-1 생성기 (로짓 척도, 과제 i, arm a):
  s0 성공확률  logit p_i = α + u_i, u_i ~ N(0, 1);  z_i ~ Bern(p_i).  T 의 결과 = z_i (결정적, 반복 동일 — 같은 산출물).
  계속 arm a ∈ {A-self, A-selfxk, A-role, B-expert}: logit q_ia = β_a + u_i + δ·z_i + s·γ_ia, γ_ia ~ N(0, σ_γ)  (z_i 조건부 + 과제×arm 상호작용)
  B-solo: logit q_iB = β_B + u_i + s·γ_iB (z_i 와 독립).
  결정성 ρ: (과제, arm) 의 잠재 결과 y_ia ~ Bern(q_ia); 반복 r 은 확률 ρ 로 y_ia, 1−ρ 로 새 Bern(q_ia). ρ=1 → 반복 동일. T 는 항상 ρ=1.
  참 oracle gap = mean_i max_a m_ia − max_a mean_i m_ia, m_ia = 반복 1회의 성공확률 (T: z_i; 그 외: ρ·y_ia + (1−ρ)·q_ia).
  목표 참 gap(0/10/15/20pp)은 상호작용 배율 s 를 이분법으로 맞춘다 (seed 마다).
F4-2 추정량:
  (i)  교차 적합 (scripts/gap_analysis.py 의 것, 홀수/짝수 반복 분할·교환 평균) + 과제 부트스트랩 CI (선택 재수행).
  (ii) 직접 + 노이즈 보정: 표본 내 gap 의 "최대의 저주" 편향을 과제 안 반복 재표집으로 추정해 뺀다 —
       bias_i = E*[max_a S̄*_ia] − max_a S̄_ia (반복 재표집 200회), corrected_i = max_a S̄_ia − bias_i,
       gap_ii = mean_i corrected_i − max_a mean_i S̄_ia, CI = 과제 부트스트랩.
  (iii) 가산 귀무 모수적 부트스트랩: 과제 효과 + arm 효과(상호작용 없음)를 적률로 맞추고 (과제, arm) 성공확률에 베타-이항 과분산을 넣어
       귀무 데이터를 300회 생성(T 는 반복 1개=결정적) → 표본 내 gap 의 귀무 분포. gap_iii = 관측 표본 내 gap − 귀무 평균,
       CI = 관측 − 귀무 [97.5%, 2.5%] 분위 (귀무 아래 statistic 의 산포를 CI 로 씀).
F4-3 전체 규칙 검정력: R1 = "CI 하한 > 0 ∧ 점추정 ≥ 10pp", R2 = "CI 하한 > 5pp". 참 gap ∈ {0,10,15,20pp} × N ∈ {60,100,150,200} × k ∈ {3,5} ×
  ρ ∈ {1.0,0.9,0.7} × seed 20 → 통과율 (Clopper-Pearson 95% 구간과 함께). X(N,k,ρ) = R1 통과율 ≥ 80% 가 되는 최소 참 gap (격자 {10,15,20,25,30}).
  부트스트랩은 검정력 연구에서 2,000회 (본 분석기는 10,000회) — 계산량 때문이며 명시한다.

    python -X utf8 scripts/gap_power.py --out evidence/week2/gap_power.json --md evidence/week2/gap_power.md [--quick]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.stats import beta as _beta

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gap_analysis as G  # noqa: E402

ARMS = G.ARMS                      # ("T", "A-self", "A-selfxk", "A-role", "B-expert", "B-solo")
CONT = [1, 2, 3, 4]                # z 조건부 계속 arm 인덱스
BSOLO = 5
ALPHA, DELTA_Z, BETA = 0.5, 2.0, np.array([0.0, 0.0, 0.3, 0.0, 0.8, 1.0])   # β_T 는 미사용, B-solo 1.0
SIGMA_U = 1.0


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def latent(n: int, seed: int, sigma_gamma: float, scale: float = 1.0):
    """과제·arm 잠재 구조 (반복 전). 반환: p_i, z_i, q[i,a] (T 열은 z), gamma."""
    rng = np.random.default_rng(seed)
    u = rng.normal(0, SIGMA_U, n)
    p = _sig(ALPHA + u)
    z = (rng.random(n) < p).astype(float)
    gamma = rng.normal(0, 1.0, (n, len(ARMS))) * sigma_gamma * scale
    q = np.zeros((n, len(ARMS)))
    q[:, 0] = z
    for a in CONT:
        q[:, a] = _sig(BETA[a] + u + DELTA_Z * z + gamma[:, a])
    q[:, BSOLO] = _sig(BETA[BSOLO] + u + gamma[:, BSOLO])
    y = (rng.random((n, len(ARMS))) < q).astype(float)
    y[:, 0] = z
    return {"p": p, "z": z, "q": q, "y": y, "rng": rng}


def per_rep_prob(L, rho: float) -> np.ndarray:
    m = rho * L["y"] + (1 - rho) * L["q"]
    if not L.get("t_noisy"):
        m[:, 0] = L["z"]                               # T 는 결정적 (교환 귀무에서만 T 도 반복 노이즈)
    return m


def oracle_gap_of(m: np.ndarray) -> float:
    return float(m.max(axis=1).mean() - m.mean(axis=0).max())


def draw_reps(L, rho: float, k: int) -> np.ndarray:
    """S[i, a, r]: 확률 ρ 로 잠재 y_ia, 아니면 새 Bern(q_ia). T 는 z_i 고정."""
    rng = L["rng"]
    n = L["p"].shape[0]
    keep = rng.random((n, len(ARMS), k)) < rho
    fresh = rng.random((n, len(ARMS), k)) < L["q"][:, :, None]
    S = np.where(keep, L["y"][:, :, None], fresh).astype(float)
    if not L.get("t_noisy"):
        S[:, 0, :] = L["z"][:, None]
    return S


def latent_exchangeable(n: int, seed: int):
    """교환 가능 귀무 (참 gap 정확히 0): 과제마다 잠재 결과 하나 y_i 를 모든 arm 이 공유하고 반복 노이즈(ρ)도 T 를 포함해 같다.
    E1 구조에서는 결정적 반복(ρ=1)이면 (과제, arm) 의 Bernoulli 실현 자체가 상호작용이라 참 gap 0 에 못 닿는다 — 크기(1종 오류) 검사는 이 귀무로 한다."""
    rng = np.random.default_rng(seed)
    u = rng.normal(0, SIGMA_U, n)
    p = _sig(ALPHA + u)
    z = (rng.random(n) < p).astype(float)
    q = np.repeat(p[:, None], len(ARMS), axis=1)
    y = np.repeat(z[:, None], len(ARMS), axis=1)
    return {"p": p, "z": z, "q": q, "y": y, "rng": rng, "t_noisy": True}   # 모든 arm 이 교환 가능하려면 T 도 같은 반복 노이즈


def calibrate_scale(n: int, seed: int, rho: float, target: float, sigma_gamma: float = 0.5) -> Tuple[float, float]:
    """참 oracle gap 이 target 이 되는 상호작용 배율 s (이분법, 같은 seed 의 난수 순서 유지).
    target 이 구조적 최소(scale 0)보다 작으면 s=0 으로 두고 실제 참 gap 을 돌려준다 (호출자가 '도달 불가' 로 표시)."""
    base = oracle_gap_of(per_rep_prob(latent(n, seed, sigma_gamma, 0.0), rho))
    if target <= base:
        return 0.0, base
    lo, hi = 0.0, 8.0
    for _ in range(40):
        mid = (lo + hi) / 2
        g = oracle_gap_of(per_rep_prob(latent(n, seed, sigma_gamma, mid), rho))
        if g < target:
            lo = mid
        else:
            hi = mid
    s = (lo + hi) / 2
    return s, oracle_gap_of(per_rep_prob(latent(n, seed, sigma_gamma, s), rho))


# ── 추정량 ────────────────────────────────────────────────────────────────
def est_crossfit(S: np.ndarray, n_boot: int, seed: int):
    gap = G.crossfit_gap(S)[0]
    lo, hi = G.bootstrap_ci(S, n_boot, seed)
    return gap, lo, hi


def _direct_parts(S: np.ndarray, rng, n_inner: int = 200):
    """corrected_i (최대의 저주 보정) 와 arm 별 과제 평균."""
    n, A, k = S.shape
    M = S.mean(axis=2)
    idx = rng.integers(0, k, (n_inner, n, A, k))                      # 과제 안 반복 재표집
    Sb = np.take_along_axis(S[None], idx, axis=3).mean(axis=3)        # [inner, n, A]
    bias = Sb.max(axis=2).mean(axis=0) - M.max(axis=1)                # [n]
    corrected = M.max(axis=1) - bias
    return corrected, M


def est_direct_corrected(S: np.ndarray, n_boot: int, seed: int):
    rng = np.random.default_rng(seed)
    corrected, M = _direct_parts(S, rng)
    n = S.shape[0]
    gap = float(corrected.mean() - M.mean(axis=0).max())
    vals = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        vals[b] = corrected[idx].mean() - M[idx].mean(axis=0).max()
    return gap, float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))


def est_additive_null(S: np.ndarray, n_null: int, seed: int):
    """가산 귀무 모수적 부트스트랩. 반환 (gap_iii, lo, hi, p_value)."""
    rng = np.random.default_rng(seed)
    n, A, k = S.shape
    M = S.mean(axis=2)
    obs = G.insample_gap(S)
    task_eff, arm_eff, grand = M.mean(axis=1), M.mean(axis=0), M.mean()
    P0 = np.clip(task_eff[:, None] + arm_eff[None, :] - grand, 0.02, 0.98)   # 가산 귀무
    # 베타-이항 과분산: (과제, arm) 안 반복 분산이 이항보다 큰 만큼 φ 를 줄인다 (계속 arm 만, T 는 결정적)
    within = S[:, 1:, :].var(axis=2, ddof=0).mean()
    binom = (P0[:, 1:] * (1 - P0[:, 1:])).mean()
    extra = max(0.0, within - binom * (k - 1) / k)                    # 관측 여분 분산 (거칠게)
    phi = max(2.0, binom / extra - 1) if extra > 1e-9 else 1e6         # 베타 정밀도: 클수록 이항에 가깝다
    null = np.empty(n_null)
    for b in range(n_null):
        pb = P0.copy()
        pb[:, 1:] = rng.beta(P0[:, 1:] * phi, (1 - P0[:, 1:]) * phi)
        Sn = (rng.random((n, A, k)) < pb[:, :, None]).astype(float)
        Sn[:, 0, :] = (rng.random((n, 1)) < P0[:, :1])                 # T: 반복 1개(결정적)
        null[b] = G.insample_gap(Sn)
    gap = float(obs - null.mean())
    lo, hi = float(obs - np.quantile(null, 0.975)), float(obs - np.quantile(null, 0.025))
    pval = float((null >= obs).mean())
    return gap, lo, hi, pval


# ── 규칙·구간 ──────────────────────────────────────────────────────────────
def rule_r1(gap, lo):
    return lo > 0 and gap >= 0.10


def rule_r2(gap, lo):
    return lo > 0.05


def clopper_pearson(x: int, n: int, alpha: float = 0.05) -> Tuple[float, float]:
    lo = 0.0 if x == 0 else float(_beta.ppf(alpha / 2, x, n - x + 1))
    hi = 1.0 if x == n else float(_beta.ppf(1 - alpha / 2, x + 1, n - x))
    return lo, hi


def fmt_rate(x: int, n: int) -> str:
    lo, hi = clopper_pearson(x, n)
    return f"{x}/{n} = {100 * x / n:.0f}% [{100 * lo:.1f}, {100 * hi:.1f}]"


# ── 실험 ────────────────────────────────────────────────────────────────────
def run_grid(targets, Ns, ks, rhos, seeds: int, n_boot: int, n_null: int, sigma_gamma: float = 0.5, log=print) -> List[Dict[str, Any]]:
    out = []
    t0 = time.time()
    for rho in rhos:
        for N in Ns:
            for k in ks:
                for tg in targets:
                    cell = {"rho": rho, "N": N, "k": k, "target": tg, "true_gaps": [], "est": {"i": [], "ii": [], "iii": []}, "unreachable": 0}
                    for s in range(seeds):
                        seed = 1000 * s + 7
                        if tg == "null":
                            L = latent_exchangeable(N, seed)
                            true_gap = oracle_gap_of(per_rep_prob(L, rho))          # = 0
                        else:
                            scale, true_gap = calibrate_scale(N, seed, rho, tg, sigma_gamma)
                            if scale == 0.0 and true_gap > tg + 1e-9:
                                cell["unreachable"] += 1
                            L = latent(N, seed, sigma_gamma, scale)
                        S = draw_reps(L, rho, k)
                        cell["true_gaps"].append(true_gap)
                        g, lo, hi = est_crossfit(S, n_boot, seed)
                        cell["est"]["i"].append((g, lo, hi))
                        g, lo, hi = est_direct_corrected(S, n_boot, seed)
                        cell["est"]["ii"].append((g, lo, hi))
                        g, lo, hi, p = est_additive_null(S, n_null, seed)
                        cell["est"]["iii"].append((g, lo, hi))
                    for e in ("i", "ii", "iii"):
                        vals = cell["est"][e]
                        cell[f"R1_{e}"] = sum(rule_r1(g, lo) for g, lo, hi in vals)
                        cell[f"R2_{e}"] = sum(rule_r2(g, lo) for g, lo, hi in vals)
                        cell[f"cover_{e}"] = sum(lo <= tgap <= hi for (g, lo, hi), tgap in zip(vals, cell["true_gaps"]))
                        cell[f"mean_{e}"] = float(np.mean([g for g, _, _ in vals]))
                    cell["true_gap_mean"] = float(np.mean(cell["true_gaps"]))
                    out.append(cell)
                    log(f"rho={rho} N={N} k={k} target={tg} true={cell['true_gap_mean']:.3f} unreach={cell['unreachable']} | mean i/ii/iii={cell['mean_i']:.3f}/{cell['mean_ii']:.3f}/{cell['mean_iii']:.3f} "
                        f"R1 i/ii/iii={cell['R1_i']}/{cell['R1_ii']}/{cell['R1_iii']} cover={cell['cover_i']}/{cell['cover_ii']}/{cell['cover_iii']} ({time.time() - t0:.0f}s)")
    return out


def find_x(cells, e: str, seeds: int, rule: str = "R1"):
    """X(N,k,ρ) = 규칙 통과율 ≥ 80% 가 되는 최소 참 gap (격자 안). 없으면 '>max'."""
    res = {}
    keys = sorted({(c["rho"], c["N"], c["k"]) for c in cells})
    for key in keys:
        cs = sorted([c for c in cells if (c["rho"], c["N"], c["k"]) == key and c["target"] != "null"], key=lambda c: c["target"])
        x = next((c["true_gap_mean"] for c in cs if c[f"{rule}_{e}"] / seeds >= 0.8), None)
        res[f"rho={key[0]},N={key[1]},k={key[2]}"] = round(100 * x, 1) if x is not None else f">{100 * cs[-1]['true_gap_mean']:.1f}"
    return res


def normal_approx_r1_at_10pp(cells, e: str, seeds: int) -> List[Dict[str, Any]]:
    """참 gap 10pp 셀에서: 추정량이 불편이고 CI 가 대칭이면 R1 통과율 ≈ P(점추정 ≥ 10pp) ≈ 50%. 관측 통과율과 정규근사 예측을 나란히."""
    rows = []
    for c in cells:
        if c["target"] == "null" or abs(c["target"] - 0.10) > 1e-9:
            continue
        g = np.array([v[0] for v in c["est"][e]])
        se = g.std(ddof=1) if len(g) > 1 else float("nan")
        bias = g.mean() - c["true_gap_mean"]
        pred = 0.5 if se == 0 else float(1 - 0.5 * (1 + math.erf((0.10 - g.mean()) / (se * math.sqrt(2)))))
        rows.append({"rho": c["rho"], "N": c["N"], "k": c["k"], "R1_observed": c[f"R1_{e}"], "normal_pred_point_ge_10pp": pred,
                     "bias": float(bias), "se": float(se)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evidence/week2/gap_power.json")
    ap.add_argument("--md", default="evidence/week2/gap_power.md")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--n-null", type=int, default=300)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    targets = ["null", 0.10, 0.15, 0.20, 0.25, 0.30]   # "null" = 교환 가능 귀무(참 gap 0); 숫자는 E1 구조에서 이분법으로 맞춘 참 gap
    Ns, ks, rhos = ([60, 200], [3], [1.0, 0.7]) if args.quick else ([60, 100, 150, 200], [3, 5], [1.0, 0.9, 0.7])
    seeds = 5 if args.quick else args.seeds
    cells = run_grid(targets, Ns, ks, rhos, seeds, args.n_boot, args.n_null)
    X = {e: find_x(cells, e, seeds) for e in ("i", "ii", "iii")}
    X2 = {e: find_x(cells, e, seeds, "R2") for e in ("i", "ii", "iii")}
    normal = {e: normal_approx_r1_at_10pp(cells, e, seeds) for e in ("i", "ii", "iii")}
    res = {"config": {"targets": targets, "N": Ns, "k": ks, "rho": rhos, "seeds": seeds, "n_boot": args.n_boot, "n_null": args.n_null,
                      "generator": {"alpha": ALPHA, "delta_z": DELTA_Z, "beta": BETA.tolist(), "sigma_u": SIGMA_U, "sigma_gamma": 0.5}},
           "cells": [{k: v for k, v in c.items() if k != "est"} for c in cells], "X_R1_min_true_gap_for_80pct": X, "X_R2": X2,
           "normal_approx_at_10pp": normal}
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    # ── markdown ──
    md = [f"# 전체 규칙 검정력 (Week2-F4-3) — seeds={seeds}, 부트스트랩 {args.n_boot}, 귀무 {args.n_null}", "",
          "추정량: (i) 교차 적합 (ii) 직접+노이즈 보정 (iii) 가산 귀무 모수적 부트스트랩. 규칙 R1 = CI 하한>0 ∧ 점추정≥10pp, R2 = CI 하한>5pp.",
          f"통과율·포함률은 {seeds}회 정확 이항(Clopper-Pearson) 95% 구간과 함께. **참 gap 이 목표값이 되도록 상호작용 배율을 seed 마다 맞춘 합성 자료**이며,",
          "(i) 의 CI 가 맞는 대상은 '2표본 선택기의 기대 성능'이고 oracle gap 검출 검증이 아니다 (D6 §2). (ii)(iii) 의 CI 는 oracle gap 을 겨냥한다.", "",
          "## 통과율 (R1) — 셀: ρ, N, k, 참 gap", "",
          "| ρ | N | k | 참 gap | i: 평균추정 · R1 · 포함 | ii: 평균추정 · R1 · 포함 | iii: 평균추정 · R1 · 포함 | R2 i/ii/iii |", "|---|---|---|---|---|---|---|---|"]
    for c in cells:
        tgt = "귀무(교환)" if c["target"] == "null" else (f"{100 * c['true_gap_mean']:.1f}pp" + (f" (목표 {int(100 * c['target'])} 도달 불가 {c['unreachable']}/{seeds})" if c["unreachable"] else ""))
        md.append(f"| {c['rho']} | {c['N']} | {c['k']} | {tgt} | " + " | ".join(
            f"{100 * c[f'mean_{e}']:.1f}pp · {fmt_rate(c[f'R1_{e}'], seeds)} · {c[f'cover_{e}']}/{seeds}" for e in ("i", "ii", "iii"))
            + f" | {c['R2_i']}/{c['R2_ii']}/{c['R2_iii']} |")
    md += ["", "## 참 gap 10pp 에서 R1 통과율 vs 정규근사 예측 P(점추정 ≥ 10pp)", "", "| 추정량 | ρ | N | k | R1 관측 | 정규근사 예측 | 편향 | se |", "|---|---|---|---|---|---|---|---|"]
    for e in ("i", "ii", "iii"):
        for r in normal[e]:
            md.append(f"| {e} | {r['rho']} | {r['N']} | {r['k']} | {fmt_rate(r['R1_observed'], seeds)} | {100 * r['normal_pred_point_ge_10pp']:.0f}% | {100 * r['bias']:+.1f}pp | {100 * r['se']:.1f}pp |")
    md += ["", "## X = R1 통과율 ≥ 80% 가 되는 최소 참 gap (pp, 격자 " + ", ".join(f"{int(100 * t)}pp" for t in targets[1:]) + " — 실제 참 gap 평균으로 표기; E1 구조의 최소 gap 아래는 도달 불가)", "",
           "| ρ, N, k | i | ii | iii |", "|---|---|---|---|"]
    for key in X["i"]:
        md.append(f"| {key} | {X['i'][key]} | {X['ii'][key]} | {X['iii'][key]} |")
    md += ["", "R2(CI 하한 > 5pp) 기준 X:", "", "| ρ, N, k | i | ii | iii |", "|---|---|---|---|"]
    for key in X2["i"]:
        md.append(f"| {key} | {X2['i'][key]} | {X2['ii'][key]} | {X2['iii'][key]} |")
    Path(args.md).write_text("\n".join(md) + "\n", encoding="utf-8")
    print("saved", args.out, args.md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
