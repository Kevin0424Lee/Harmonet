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
        assert r0["verdict"] == "미확인" and r0["gain"] < 0.05, (L, r0["gain"], r0["p_value"])
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
