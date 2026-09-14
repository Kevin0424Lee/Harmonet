"""
scripts/gap_analysis.py — 교차 적합 gap 분석 (Week2-D6, 설계 §4). 풀 무관. 유료 호출 0.

입력 행: {"task_id", "arm", "rep"(1..k), "hidden_pass"(bool 만), "cost_usd"(float|None), "budget_refused"(bool)} (benchmark/arms.py 출력과 동일)
  → 텐서 S[task, arm, rep] ∈ {0,1}. 중복 (task, arm, rep) 은 예외, hidden_pass 가 bool 이 아니면("True"/"False" 문자열 포함) 예외 (F3).

통계량:
  - arm 별 성공률 / $ 평균(미측정이 하나라도 있으면 None) / 거부율.
  - 반복 집합 분할: rep 홀수 = 집합 1, 짝수 = 집합 2 (k=3 → {1,3} / {2}). 교차 적합 gap = ½[gap(선택 1 → 평가 2) + gap(선택 2 → 평가 1)],
    gap(sel→eval) = mean_task S_eval[task, best_arm_task(sel)] − mean_task S_eval[task, best_fixed(sel)].
    best_arm_task = 과제별 집합 sel 평균 성공률 argmax (동점은 ARMS 순서 앞), best_fixed = 과제 평균 성공률 argmax (과제와 무관).
  - 표본 내 gap(진단): 전체 데이터에서 선택·평가. 상한이 아니다.
  - 과제 단위 부트스트랩 (과제 재표집, 반복은 과제 안에 중첩), 복제마다 선택 단계를 다시 수행, 기본 10,000회 → 백분위 95% CI.
  - 판정: CI 하한 > 0 ∧ 점추정 ≥ 0.10 → "통과", 그 외 "미확인". ("없음" 은 없다.)
  - power.json: 과제별 교차 적합 차이(사후 선택 − 고정)의 표준편차 σ 로 N = ((z_0.975 + z_0.8)·σ / Δ)², Δ = 0.10.
  - 경고: 모든 (과제, arm) 에서 반복 간 성공이 동일하면 "반복이 결정적 — 반복 노이즈를 재지 못했다".

    python -X utf8 scripts/gap_analysis.py rows.json --out gap.json --power power.json
    python -X utf8 scripts/gap_analysis.py --synthetic            # 합성 검증 (a)(b)(c)(d)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

ARMS = ("T", "A-self", "A-selfxk", "A-role", "B-expert", "B-solo")
DELTA = 0.10


def _hidden_pass(r: Dict[str, Any]) -> bool:
    """hidden_pass 는 bool 만 받는다 (F3). 문자열 "True"/"False"·0/1·None 은 예외 — hidden_guard 와 같은 방침(조용한 해석 금지)."""
    if "hidden_pass" not in r:
        raise ValueError(f"행에 hidden_pass 가 없다: {r.get('task_id')}/{r.get('arm')}/{r.get('rep')}")
    v = r["hidden_pass"]
    if not isinstance(v, bool):
        raise ValueError(f"hidden_pass 는 bool 이어야 한다, {v!r} ({type(v).__name__}) — {r.get('task_id')}/{r.get('arm')}/{r.get('rep')}")
    return v


def tensor(rows: Sequence[Dict[str, Any]], arms: Sequence[str] = ARMS):
    seen = set()
    for r in rows:                                                  # F3: 중복 (task, arm, rep) 은 덮어쓰지 않고 예외
        key = (r["task_id"], r["arm"], int(r["rep"]))
        if key in seen:
            raise ValueError(f"중복 행: task={key[0]} arm={key[1]} rep={key[2]} — 같은 셀을 두 번 채울 수 없다")
        seen.add(key)
        if r["arm"] not in arms:
            raise ValueError(f"알 수 없는 arm {r['arm']!r}")
    tasks = sorted({r["task_id"] for r in rows})
    reps = sorted({int(r["rep"]) for r in rows})
    S = np.full((len(tasks), len(arms), len(reps)), np.nan)
    ti, ai, ri = {t: i for i, t in enumerate(tasks)}, {a: i for i, a in enumerate(arms)}, {k: i for i, k in enumerate(reps)}
    for r in rows:
        S[ti[r["task_id"]], ai[r["arm"]], ri[int(r["rep"])]] = 1.0 if _hidden_pass(r) else 0.0
    if np.isnan(S).any():
        missing = int(np.isnan(S).sum())
        raise ValueError(f"불완전한 설계: {missing} 칸이 비어 있다 (과제×arm×반복 전부 있어야 한다)")
    return S, tasks, reps


def _gap(S_sel: np.ndarray, S_eval: np.ndarray):
    """선택 집합 평균으로 고르고 평가 집합 평균으로 잰다. 둘 다 [task, arm]."""
    best_task = np.argmax(S_sel, axis=1)                          # 동점 → 앞 arm (np.argmax 규칙)
    best_fixed = int(np.argmax(S_sel.mean(axis=0)))
    oracle = S_eval[np.arange(S_eval.shape[0]), best_task]
    fixed = S_eval[:, best_fixed]
    return float(oracle.mean() - fixed.mean()), oracle - fixed, best_fixed


def crossfit_gap(S: np.ndarray):
    """(교차 적합 gap, 과제별 차이 벡터(두 방향 평균), 최선 고정 arm 두 방향)."""
    k = S.shape[2]
    m1, m2 = [i for i in range(k) if (i + 1) % 2 == 1], [i for i in range(k) if (i + 1) % 2 == 0]
    if not m2:
        raise ValueError("반복 k ≥ 2 여야 교차 적합이 가능하다")
    A1, A2 = S[:, :, m1].mean(axis=2), S[:, :, m2].mean(axis=2)
    g12, d12, f12 = _gap(A1, A2)
    g21, d21, f21 = _gap(A2, A1)
    return 0.5 * (g12 + g21), 0.5 * (d12 + d21), (f12, f21)


def insample_gap(S: np.ndarray) -> float:
    M = S.mean(axis=2)
    return _gap(M, M)[0]


def bootstrap_ci(S: np.ndarray, n_boot: int = 10000, seed: int = 0, alpha: float = 0.05):
    rng = np.random.default_rng(seed)
    T = S.shape[0]
    vals = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, T, T)                             # 과제 재표집 (반복은 과제 안에 중첩)
        vals[b] = crossfit_gap(S[idx])[0]                       # 복제마다 선택 단계 재수행
    return float(np.quantile(vals, alpha / 2)), float(np.quantile(vals, 1 - alpha / 2))


def per_arm(rows: Sequence[Dict[str, Any]], arms=ARMS) -> Dict[str, Any]:
    out = {}
    for a in arms:
        r = [x for x in rows if x["arm"] == a]
        if not r:
            continue
        costs = [x.get("cost_usd") for x in r]
        out[a] = {"n": len(r), "success": sum(_hidden_pass(x) for x in r) / len(r),
                  "cost_usd_mean": None if any(c is None for c in costs) else float(np.mean(costs)),
                  "n_unpriced": sum(c is None for c in costs), "refused_rate": sum(bool(x.get("budget_refused")) for x in r) / len(r)}
    return out


def analyze(rows: Sequence[Dict[str, Any]], n_boot: int = 10000, seed: int = 0) -> Dict[str, Any]:
    S, tasks, reps = tensor(rows)
    gap, diffs, fixed = crossfit_gap(S)
    lo, hi = bootstrap_ci(S, n_boot, seed)
    deterministic = bool(np.all(S.std(axis=2) == 0))
    verdict = "통과" if (lo > 0 and gap >= DELTA) else "미확인"
    sigma = float(diffs.std(ddof=1)) if len(diffs) > 1 else float("nan")
    z = 1.959963984540054 + 0.8416212335729143
    n_needed = int(math.ceil((z * sigma / DELTA) ** 2)) if sigma > 0 else 0
    return {"n_tasks": len(tasks), "k": len(reps), "n_boot": n_boot, "per_arm": per_arm(rows),
            "crossfit_gap": gap, "ci95": [lo, hi], "insample_gap_diagnostic": insample_gap(S),
            "best_fixed_arm": [ARMS[fixed[0]], ARMS[fixed[1]]], "verdict": verdict, "delta": DELTA,
            "warnings": (["반복이 결정적 — 모든 (과제, arm) 에서 반복 간 성공이 같다. 반복 노이즈를 재지 못했으며 교차 적합의 의미가 약하다"] if deterministic else []),
            "power": {"sigma_task_diff": sigma, "delta": DELTA, "alpha": 0.05, "power": 0.8, "n_needed": n_needed,
                      "note": "N = ((z_0.975 + z_0.8)·σ/Δ)², σ = 과제별 교차 적합 차이의 표준편차 (파일럿 추정)"}}


# ═══════════════════════════════════════════════════════════════════════════
# Week2-H2: 정책 이득 추정기 — oracle 상한이 아니라 "결정 시점 특징으로 arm 을 고르는 정책" 의 이득.
#
# 입력 행: 위 스키마 + "features": {"visible": str, "n_failed": int, "error_kind": str, "artifact_chars": num, "s0_cost": num}  (§8 신호 형식)
#   k=1 (과제마다 arm 당 1회). rows → Y[task, arm] ∈ {0,1}, C[task, arm] = cost_usd, 특징은 과제당 하나(모든 arm 행에 같은 값).
# 학습기 2종 (사전 등록):
#   P1 조회표: 가시 검증 범주(visible)별로 학습 과제에서 성공률이 최대인 arm (동점 ARMS 순서 앞). 학습에 없는 범주 → 최선 고정 arm.
#   P2 L2 로지스틱: arm 마다 P(성공 | x) 를 로지스틱(특징 표준화, 범주 one-hot, ridge λ=1.0, IRLS 8회)으로 적합 → argmax_a.
# 평가: 과제 K=5 겹 교차 검증 × R=20 회 셔플. 겹마다 최선 고정 arm 도 학습 과제에서 고른다.
#   통계량 = 검증 과제 평균(정책이 고른 arm 의 성공 − 최선 고정 arm 의 성공), 겹·셔플 평균. 예산 매칭용으로 고른 arm 의 실제 $ 도 같이 집계.
# 귀무: **특징 벡터를 과제 사이에서 순열**(결과 고정) B=2000 → 통계량 귀무분포 → p = P(null ≥ obs).
#   arm 라벨 순열이 아닌 이유: 우리 질문은 "특징이 결과를 예측하는가" 이지 "arm 간 차이가 있는가" 가 아니다. arm 라벨을 섞으면 최선 고정
#   arm 의 이점까지 없애 버려 귀무가 너무 넓어지고, 특징을 섞으면 과제×arm 결과 구조(고정 arm 의 우위, 과제 난이도)는 그대로 둔 채
#   특징–결과 연결만 끊는다 — 정확히 정책 이득의 귀무다.
# CI: 과제 부트스트랩(복제마다 CV 전체 재수행) 1000회.
# 규칙 R2: p < 0.05 ∧ 점추정 ≥ 10pp → "통과", 그 외 "미확인".
# ═══════════════════════════════════════════════════════════════════════════

FEATURE_NUM = ("n_failed", "artifact_chars", "s0_cost")
FEATURE_CAT = ("visible", "error_kind")
P2_LAMBDA, P2_ITERS = 1.0, 8
CV_K, CV_R = 5, 20


def policy_tensor(rows: Sequence[Dict[str, Any]], arms: Sequence[str] = ARMS):
    """rows → (Y[n, A], C[n, A], feats(list of dict, 과제 순), tasks). k=1 만 허용 (rep 이 여럿이면 예외)."""
    S, tasks, reps = tensor(rows, arms)
    if len(reps) != 1:
        raise ValueError(f"정책 이득 추정은 k=1 행을 받는다 (rep 종류 {reps})")
    ti, ai = {t: i for i, t in enumerate(tasks)}, {a: i for i, a in enumerate(arms)}
    C = np.full((len(tasks), len(arms)), np.nan)
    feats: List[Optional[Dict[str, Any]]] = [None] * len(tasks)
    for r in rows:
        C[ti[r["task_id"]], ai[r["arm"]]] = np.nan if r.get("cost_usd") is None else float(r["cost_usd"])
        f = r.get("features")
        if not isinstance(f, dict):
            raise ValueError(f"features 누락: {r['task_id']}/{r['arm']}")
        if feats[ti[r["task_id"]]] is None:
            feats[ti[r["task_id"]]] = f
        elif feats[ti[r["task_id"]]] != f:
            raise ValueError(f"같은 과제의 arm 행마다 features 가 다르다: {r['task_id']}")
    return S[:, :, 0], C, feats, tasks


def design_matrix(feats: Sequence[Dict[str, Any]], cats: Optional[Dict[str, List[str]]] = None):
    """수치 특징 + 범주 one-hot (+절편). 표준화는 호출자가 학습 과제 통계로 한다. cats 는 범주 수준 목록(학습에서 고정)."""
    if cats is None:
        cats = {c: sorted({str(f[c]) for f in feats}) for c in FEATURE_CAT}
    cols = []
    for f in feats:
        row = [float(f[k]) for k in FEATURE_NUM]
        for c in FEATURE_CAT:
            row += [1.0 if str(f[c]) == lvl else 0.0 for lvl in cats[c]]
        cols.append(row)
    return np.array(cols, dtype=float), cats


def _fit_logistic_batch(X: np.ndarray, Y: np.ndarray, lam: float = P2_LAMBDA, iters: int = P2_ITERS) -> np.ndarray:
    """X[n, d] (절편 포함), Y[n, A] → beta[A, d]. arm 배치 IRLS, ridge(절편 제외)."""
    n, d = X.shape
    A = Y.shape[1]
    beta = np.zeros((A, d))
    pen = np.full(d, lam); pen[0] = 0.0
    for _ in range(iters):
        eta = X @ beta.T                                      # [n, A]
        mu = 1 / (1 + np.exp(-eta))
        w = np.clip(mu * (1 - mu), 1e-6, None)
        z = eta + (Y - mu) / w
        H = np.einsum("na,nd,ne->ade", w, X, X) + np.diag(pen)[None]
        g = np.einsum("na,nd->ad", w * z, X)
        beta = np.linalg.solve(H, g[..., None])[..., 0]
    return beta


def _standardize(Xtr: np.ndarray, Xte: np.ndarray, n_num: int):
    mu, sd = Xtr[:, :n_num].mean(axis=0), Xtr[:, :n_num].std(axis=0) + 1e-9
    Xtr = Xtr.copy(); Xte = Xte.copy()
    Xtr[:, :n_num] = (Xtr[:, :n_num] - mu) / sd
    Xte[:, :n_num] = (Xte[:, :n_num] - mu) / sd
    return np.hstack([np.ones((len(Xtr), 1)), Xtr]), np.hstack([np.ones((len(Xte), 1)), Xte])


def policy_p1(train_idx, test_idx, Y, feats, fixed_arm):
    cat = np.array([str(f["visible"]) for f in feats])
    choice = {}
    for lvl in set(cat[train_idx]):
        m = train_idx[cat[train_idx] == lvl]
        choice[lvl] = int(np.argmax(Y[m].mean(axis=0)))
    return np.array([choice.get(cat[i], fixed_arm) for i in test_idx])


def policy_p2(train_idx, test_idx, Y, X, fixed_arm):
    Xtr, Xte = _standardize(X[train_idx], X[test_idx], len(FEATURE_NUM))
    beta = _fit_logistic_batch(Xtr, Y[train_idx])
    return np.argmax(Xte @ beta.T, axis=1)


def _cv_gain(Y: np.ndarray, C: np.ndarray, feats, X: np.ndarray, learner: str, rng, K: int = CV_K, R: int = CV_R):
    """K 겹 × R 셔플. 반환 (gain 평균, 정책 $ 평균, 고정 $ 평균)."""
    n = Y.shape[0]
    gains, cost_pol, cost_fix = [], [], []
    for _ in range(R):
        perm = rng.permutation(n)
        folds = np.array_split(perm, K)
        for f in range(K):
            te = folds[f]
            tr = np.concatenate([folds[j] for j in range(K) if j != f])
            fixed = int(np.argmax(Y[tr].mean(axis=0)))
            pick = policy_p1(tr, te, Y, feats, fixed) if learner == "P1" else policy_p2(tr, te, Y, X, fixed)
            gains.append((Y[te, pick] - Y[te, fixed]).mean())
            cost_pol.append(np.nanmean(C[te, pick])); cost_fix.append(np.nanmean(C[te, fixed]))
    return float(np.mean(gains)), float(np.mean(cost_pol)), float(np.mean(cost_fix))


def policy_gain(rows: Sequence[Dict[str, Any]], learner: str = "P1", n_perm: int = 2000, n_boot: int = 1000, seed: int = 0,
                with_ci: bool = True, R: int = CV_R) -> Dict[str, Any]:
    if learner not in ("P1", "P2"):
        raise ValueError(learner)
    Y, C, feats, tasks = policy_tensor(rows)
    X, cats = design_matrix(feats)
    rng = np.random.default_rng(seed)
    obs, cpol, cfix = _cv_gain(Y, C, feats, X, learner, np.random.default_rng(seed + 1), R=R)
    null = np.empty(n_perm)
    for b in range(n_perm):                                 # 특징 순열(결과 고정)
        p = rng.permutation(len(tasks))
        fp = [feats[i] for i in p]
        null[b] = _cv_gain(Y, C, fp, X[p], learner, np.random.default_rng(seed + 1), R=R)[0]
    pval = float((null >= obs).mean())
    out = {"learner": learner, "n_tasks": len(tasks), "gain": obs, "p_value": pval, "null_mean": float(null.mean()),
           "cost_policy_usd": cpol, "cost_fixed_usd": cfix, "n_perm": n_perm, "cv": {"K": CV_K, "R": R},
           "verdict": "통과" if (pval < 0.05 and obs >= 0.10) else "미확인", "rule": "R2 = p<0.05 ∧ 정책 이득 ≥ 10pp"}
    if with_ci:
        vals = np.empty(n_boot)
        for b in range(n_boot):                             # 과제 부트스트랩, 복제마다 CV 전체 재수행
            idx = rng.integers(0, len(tasks), len(tasks))
            vals[b] = _cv_gain(Y[idx], C[idx], [feats[i] for i in idx], X[idx], learner, np.random.default_rng(seed + 2 + b), R=R)[0]
        out["ci95"] = [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))]
        out["n_boot"] = n_boot
    return out


# ── 합성 검증 ────────────────────────────────────────────────────────────
def synth_rows(n_tasks: int, k: int, seed: int, interaction: float = 0.0, base: float = 0.5, deterministic: bool = False, cost=0.01):
    """arm 별 기저 성공률 + (interaction > 0 이면) 과제별로 하나의 arm 이 +interaction 만큼 잘 푸는 상호작용."""
    rng = np.random.default_rng(seed)
    arm_base = base + rng.normal(0, 0.05, len(ARMS))
    best = rng.integers(0, len(ARMS), n_tasks)
    task_eff = rng.normal(0, 0.15, n_tasks)
    rows = []
    for t in range(n_tasks):
        for a, arm in enumerate(ARMS):
            p = np.clip(arm_base[a] + task_eff[t] + (interaction if a == best[t] else 0.0), 0.02, 0.98)
            outcome_det = rng.random() < p
            for rep in range(1, k + 1):
                passed = outcome_det if deterministic else (rng.random() < p)
                rows.append({"task_id": f"s{t}", "arm": arm, "rep": rep, "hidden_pass": bool(passed), "cost_usd": cost, "budget_refused": False})
    return rows


def _synth_P(n_tasks: int, seed: int, interaction: float, base: float = 0.5):
    rng = np.random.default_rng(seed)
    arm_base = base + rng.normal(0, 0.05, len(ARMS))
    best = rng.integers(0, len(ARMS), n_tasks)
    task_eff = rng.normal(0, 0.15, n_tasks)
    return np.clip(arm_base[None, :] + task_eff[:, None] + interaction * (np.arange(len(ARMS))[None, :] == best[:, None]), 0.02, 0.98)


def oracle_gap(n_tasks: int, seed: int, interaction: float) -> float:
    """참 확률 P 의 oracle gap: E[max_arm P] − max_arm E[P]. 교차 적합 통계량의 추정 대상이 **아니다** (아래 estimand 참조)."""
    P = _synth_P(n_tasks, seed, interaction)
    return float(P.max(axis=1).mean() - P.mean(axis=0).max())


def crossfit_estimand(n_tasks: int, k: int, seed: int, interaction: float, n_mc: int = 300) -> float:
    """교차 적합 통계량의 추정 대상 = 같은 P 에서 데이터를 거듭 뽑았을 때 통계량의 기대값 (몬테카를로).
    k 가 작으면 집합 1 의 선택이 잡음 때문에 자주 틀리므로 이 값은 oracle gap 보다 작다 — 설계 §4-3 의 경고가 그 뜻이다."""
    P = _synth_P(n_tasks, seed, interaction)
    rng = np.random.default_rng(seed + 10_000)
    vals = []
    for _ in range(n_mc):
        S = (rng.random((n_tasks, len(ARMS), k)) < P[:, :, None]).astype(float)
        vals.append(crossfit_gap(S)[0])
    return float(np.mean(vals))


def synthetic(n_boot: int = 10000, seeds: int = 20, n_tasks: int = 300, k: int = 3) -> Dict[str, Any]:
    a_pass = 0
    for s in range(seeds):
        r = analyze(synth_rows(n_tasks, k, s, 0.0), n_boot, seed=s)
        a_pass += r["verdict"] == "통과"
    b_cover = 0
    b_gaps = []
    for s in range(seeds):
        r = analyze(synth_rows(n_tasks, k, s, 0.10), n_boot, seed=s)
        est = crossfit_estimand(n_tasks, k, s, 0.10)
        b_gaps.append({"crossfit_gap": r["crossfit_gap"], "estimand": est, "oracle_gap": oracle_gap(n_tasks, s, 0.10), "ci95": r["ci95"]})
        b_cover += r["ci95"][0] <= est <= r["ci95"][1]
    c = analyze(synth_rows(50, k, 0, 0.0, deterministic=True), 200, seed=0)
    d = per_arm([{"task_id": "x", "arm": "T", "rep": 1, "hidden_pass": True, "cost_usd": None, "budget_refused": False},
                 {"task_id": "y", "arm": "T", "rep": 1, "hidden_pass": True, "cost_usd": 0.1, "budget_refused": False}])
    return {"a_no_interaction_pass_rate": a_pass / seeds, "a_seeds": seeds, "a_criterion": "≤ 0.08",
            "b_coverage": b_cover / seeds, "b_criterion": "≥ 0.90 (CI 가 교차 적합 추정 대상을 포함)", "b_examples": b_gaps[:3],
            "b_note": "estimand = 같은 P 에서 데이터를 거듭 뽑았을 때의 교차 적합 gap 기대값. k=3 의 잡음 선택 때문에 oracle gap 보다 작다 — 10pp 문턱은 이 값에 적용된다",
            "c_deterministic_warning": bool(c["warnings"]), "d_unpriced_cost_none": d["T"]["cost_usd_mean"] is None and d["T"]["n_unpriced"] == 1,
            "n_boot": n_boot, "n_tasks": n_tasks, "k": k}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--power")
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--seeds", type=int, default=20)
    args = ap.parse_args()
    if args.synthetic:
        res = synthetic(args.n_boot, args.seeds)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if args.out:
            Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    rows = rows["rows"] if isinstance(rows, dict) else rows
    res = analyze(rows, args.n_boot)
    print(json.dumps({k: v for k, v in res.items() if k != "power"}, ensure_ascii=False, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.power:
        Path(args.power).write_text(json.dumps(res["power"], ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
