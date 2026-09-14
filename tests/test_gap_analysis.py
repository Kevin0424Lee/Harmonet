"""Week2-D6: 교차 적합 gap 분석의 합성 검증. 전체 규모(10,000 부트스트랩)는 `scripts/gap_analysis.py --synthetic` 로 따로 돌리고
결과를 evidence/week2/gap_synthetic.json 에 둔다. 여기서는 같은 절차를 축소 규모로 확인한다."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gap_analysis as G  # noqa: E402


def test_a_no_interaction_rarely_passes():
    n_pass = sum(G.analyze(G.synth_rows(300, 3, s, 0.0), n_boot=300, seed=s)["verdict"] == "통과" for s in range(20))
    assert n_pass / 20 <= 0.08, n_pass


def test_b_ci_covers_crossfit_estimand():
    cover = 0
    for s in range(20):
        r = G.analyze(G.synth_rows(300, 3, s, 0.10), n_boot=500, seed=s)
        est = G.crossfit_estimand(300, 3, s, 0.10, n_mc=100)
        cover += r["ci95"][0] <= est <= r["ci95"][1]
    assert cover / 20 >= 0.90, cover


def test_c_deterministic_repeats_warn():
    r = G.analyze(G.synth_rows(40, 3, 0, 0.0, deterministic=True), n_boot=100)
    assert r["warnings"] and "결정적" in r["warnings"][0]
    r2 = G.analyze(G.synth_rows(40, 3, 0, 0.0), n_boot=100)
    assert not r2["warnings"]


def test_d_unpriced_cost_is_none():
    rows = G.synth_rows(5, 2, 0)
    rows[0]["cost_usd"] = None
    pa = G.per_arm(rows)
    assert pa["T"]["cost_usd_mean"] is None and pa["T"]["n_unpriced"] == 1 and abs(pa["A-self"]["cost_usd_mean"] - 0.01) < 1e-12


def test_incomplete_design_rejected():
    rows = G.synth_rows(3, 2, 0)[:-1]
    with pytest.raises(ValueError, match="불완전"):
        G.tensor(rows)


def test_crossfit_known_case():
    """과제 2개, arm 6, k=2: 과제 0 은 arm 1 만 성공, 과제 1 은 arm 2 만 성공 (결정적) → 사후 선택 1.0, 최선 고정 0.5, gap 0.5."""
    S = np.zeros((2, 6, 2)); S[0, 1, :] = 1; S[1, 2, :] = 1
    gap, diffs, fixed = G.crossfit_gap(S)
    assert abs(gap - 0.5) < 1e-12 and G.insample_gap(S) == 0.5
