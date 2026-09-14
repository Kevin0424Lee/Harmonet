"""Week2-G2: (iii) v2 — 독립 바닥 위의 초과분. 축소 규모 검증 (전체는 evidence/week2/gap_floor_g2.json)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gap_floor as F  # noqa: E402


def test_rho_hat_tracks_true_rho():
    for rho in (1.0, 0.7):
        S, _ = F.make_S(300, 7, rho, 5, 0.0, 0.0, 0.0)
        r = F.estimate_rho(S, F.fit_additive(S.mean(axis=2)))
        assert r[0] == 1.0 and abs(r[1:].mean() - rho) < 0.1, (rho, r)


def test_no_interaction_gives_near_zero_excess_and_no_pass():
    ex, passes = [], 0
    for s in range(6):
        S, _ = F.make_S(100, 1000 * s + 7, 1.0, 3, 0.0, 0.0, 2.0)
        r = F.analyze_floor(S, 400, s, with_ci=False)
        ex.append(r["excess"]); passes += r["verdict"] == "통과"
    assert abs(np.mean(ex)) <= 0.03 and passes == 0, (np.mean(ex), passes)


def test_floor_is_positive_under_deterministic_repeats():
    S, tg = F.make_S(100, 7, 1.0, 3, 0.0, 0.0, 2.0)
    r = F.analyze_floor(S, 400, 0, with_ci=False)
    assert r["floor"] > 0.10 and r["observed_insample_gap"] > 0.10     # 바닥만으로 10pp 를 넘는다 (G1 의 자명 통과 원인)


def test_additive_fit_shape_and_range():
    M = np.array([[1, 0, 1], [0, 0, 1], [1, 1, 1], [0, 0, 0]], dtype=float)
    P = F.fit_additive(M)
    assert P.shape == M.shape and (P > 0).all() and (P < 1).all()
    assert P[2].mean() > P[3].mean() and P[:, 2].mean() > P[:, 1].mean()
