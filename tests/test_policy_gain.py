"""Week2-H2: 정책 이득 추정기 (P1 조회표 / P2 L2 로지스틱, K=5 CV, 특징 순열 귀무, R2). 축소 규모 — 전체는 evidence/week2/policy_gain_h2.json."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gap_analysis as G   # noqa: E402
import policy_gain as PG   # noqa: E402


def test_true_gain_zero_when_features_independent_and_positive_with_signal():
    g0 = PG.true_gain(PG.generate(200, 11, 0.0, 1.0), 0.0)
    g1 = PG.true_gain(PG.generate(200, 11, 1.0, 1.0, delta=3.0), 1.0)
    assert abs(g0) < 1e-9 and g1 > 0.05


def test_p1_and_p2_no_pass_under_null_and_detect_signal():
    rows0 = PG.rows_from(PG.generate(200, 11, 0.0, 1.0))
    rows1 = PG.rows_from(PG.generate(300, 11, 1.0, 1.0, delta=3.0))
    for L in ("P1", "P2"):
        r0 = G.policy_gain(rows0, L, n_perm=60, n_boot=0, seed=1, with_ci=False, R=3)
        assert r0["diag_R2"] == "미확인" and r0["gain"] < 0.05, (L, r0["gain"], r0["p_value"])
    r1 = G.policy_gain(rows1, "P2", n_perm=60, n_boot=0, seed=1, with_ci=False, R=3)
    assert r1["p_value"] < 0.05 and r1["gain"] > 0.03, r1


def test_policy_tensor_requires_features_and_k1():
    rows = PG.rows_from(PG.generate(20, 1, 0.0, 1.0))
    bad = [dict(r) for r in rows]
    del bad[0]["features"]
    with pytest.raises(ValueError, match="features"):
        G.policy_tensor(bad)
    two = rows + [dict(r, rep=2) for r in rows]
    with pytest.raises(ValueError, match="k=1"):
        G.policy_tensor(two)


def test_ci_and_costs_present():
    rows = PG.rows_from(PG.generate(60, 3, 0.5, 1.0))
    r = G.policy_gain(rows, "P1", n_perm=30, n_boot=20, seed=0, R=2)
    assert len(r["ci95"]) == 2 and r["ci95"][0] <= r["gain"] <= r["ci95"][1] + 0.05
    assert r["cost_policy_usd"] >= 0 and r["cost_fixed_usd"] > 0


# ── Week2-J1: 입력 가드·부트스트랩 누수·순열 p ────────────────────────────
def test_guard_infra_row_rejected():
    rows = PG.rows_from(PG.generate(10, 1, 0.0, 1.0))
    rows[3] = dict(rows[3], infra=True)
    with pytest.raises(ValueError, match="infra=True"):
        G.policy_tensor(rows)


def test_guard_hidden_exposed_must_be_explicit_false():
    rows = PG.rows_from(PG.generate(10, 1, 0.0, 1.0))
    for bad in (None, "False", 0, True):
        r2 = [dict(r) for r in rows]
        if bad is None:
            del r2[0]["hidden_exposed"]
        else:
            r2[0]["hidden_exposed"] = bad
        with pytest.raises(ValueError, match="hidden_exposed"):
            G.policy_tensor(r2)


def test_guard_unpriced_cost_gives_none_not_nanmean():
    rows = PG.rows_from(PG.generate(30, 2, 0.0, 1.0))
    rows = [dict(r, cost_usd=None) if r["task_id"] == "s1" else r for r in rows]     # 과제 하나 전체 미측정
    r = G.policy_gain(rows, "P1", n_perm=5, n_boot=0, seed=0, with_ci=False, R=2)
    assert r["n_unpriced"] == len(G.ARMS) and r["cost_policy_usd"] is None and r["cost_fixed_usd"] is None


def test_group_folds_keep_duplicated_ids_on_one_side():
    rng = np.random.default_rng(0)
    groups = rng.integers(0, 40, 100)                      # 부트스트랩 복제처럼 같은 원본 id 가 여러 행
    folds = G._group_folds(groups, rng, 5)
    assert sorted(np.concatenate(folds).tolist()) == list(range(100))
    for f in folds:
        others = np.concatenate([g for g in folds if g is not f])
        assert not set(groups[f]) & set(groups[others])


def test_perm_pvalue_is_count_plus_one_over_B_plus_one():
    rows = PG.rows_from(PG.generate(40, 3, 0.0, 1.0))
    r = G.policy_gain(rows, "P1", n_perm=9, n_boot=0, seed=0, with_ci=False, R=1)
    assert r["p_value"] >= 1 / 10 and abs(r["p_value"] * 10 - round(r["p_value"] * 10)) < 1e-9


# ── Week2-J4: 확인 단계 판정 (정확 McNemar 단측, 학습 없음) ─────────────
def test_mcnemar_exact_onesided_and_confirm_rule():
    assert abs(G.mcnemar_exact_onesided(8, 1) - 10 / 512) < 1e-12 and G.mcnemar_exact_onesided(0, 0) == 1.0
    Y = np.zeros((40, 6)); Y[:, 4] = 1                      # â = B-expert 전부 성공
    Y[:30, 4] = 0; Y[:30, 1] = 1                             # 30 과제는 A-self 만 성공
    pick = np.where(np.arange(40) < 30, 1, 4)
    r = G.confirm_test(Y, pick, a_hat=4, n_boot=50, seed=0)
    assert r["b_policy_only"] == 30 and r["c_fixed_only"] == 0 and r["mean_d"] == 0.75 and r["verdict"] == "통과"
    r2 = G.confirm_test(Y, np.full(40, 4), a_hat=4, n_boot=0)
    assert r2["mean_d"] == 0.0 and r2["p_mcnemar_onesided"] == 1.0 and r2["verdict"] == "미확인" and r2["ci95"] is None


# ── Week2-K5: nested 특징 선택 CV ─────────────────────────────────────────
def test_nested_selection_runs_and_is_flagged():
    rows = PG.rows_from(PG.generate(60, 5, 1.0, 1.0, delta=3.0))
    for r in rows:                                          # 메뉴 = 정보 5 + 잡음 4
        r["features"] = {**r["features"], **{f"noise_{j}": float(j + hash(r["task_id"]) % 7) for j in range(4)}}
    menu = {"num": list(G.FEATURE_NUM) + [f"noise_{j}" for j in range(4)], "cat": list(G.FEATURE_CAT)}
    r_nested = G.policy_gain(rows, "P2", n_perm=0, n_boot=0, seed=0, with_ci=False, R=2, spec=menu, nested_max_selected=5)
    r_plain = G.policy_gain(rows, "P2", n_perm=0, n_boot=0, seed=0, with_ci=False, R=2, spec=menu)
    assert r_nested["nested_selection"] is True and r_plain["nested_selection"] is False and r_nested["p_value"] is None
    assert isinstance(r_nested["gain"], float) and r_nested["gain"] != r_plain["gain"]


def test_guard_incomplete_arm_record_rejected():
    rows = PG.rows_from(PG.generate(10, 1, 0.0, 1.0))
    rows[2] = dict(rows[2], incomplete=True)
    with pytest.raises(ValueError, match="미완료"):
        G.policy_tensor(rows)
