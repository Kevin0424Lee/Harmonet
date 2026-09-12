"""
tests/test_resonance.py
=======================
ResonanceDetector 단위 테스트 (Kuramoto·TDA 는 tests/legacy/) — CI 회귀 방지.
"""

import time
import numpy as np
import pytest

from harmonet.field import DataUniverseField, Seed
from harmonet.resonance import ResonanceDetector, ResonanceEvent

DIM  = 16
GRID = 8

def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-8)

def _rand_unit(dim: int = DIM) -> np.ndarray:
    return _unit(np.random.randn(dim).astype(np.float32))

def _make_seed(
    seed_id="s1", creator="A", dim=DIM,
    freq_vec=None, energy=0.8, phase=0.0,
) -> Seed:
    return Seed(
        id=seed_id,
        creator_id=creator,
        frequency=freq_vec if freq_vec is not None else _rand_unit(dim),
        payload=_rand_unit(dim),
        rule_description="test",
        energy=energy,
        phase=phase,
        ttl_seconds=300.0,
    )

@pytest.fixture
def universe():
    return DataUniverseField(dim=DIM, grid_size=GRID)

@pytest.fixture
def detector():
    omega = _rand_unit()
    return ResonanceDetector(
        agent_id="tester",
        domain_vector=omega,
        resonance_threshold=0.5,
        min_seed_energy=0.05,
    )


# ── ResonanceDetector 초기화 ──────────────────────────────────────

class TestDetectorInit:
    def test_agent_id_stored(self, detector):
        assert detector.agent_id == "tester"

    def test_omega_normalized(self, detector):
        assert abs(np.linalg.norm(detector.omega) - 1.0) < 1e-5

    def test_default_delta(self, detector):
        assert detector.delta == 0.5

    def test_resonance_history_empty(self, detector):
        assert len(detector.resonance_history) == 0

    def test_adaptive_delta_attributes(self, detector):
        assert hasattr(detector, "delta_min")
        assert hasattr(detector, "delta_max")
        assert hasattr(detector, "_scan_count")
        assert hasattr(detector, "_recent_similarities")
        assert detector.delta_min < detector.delta_max


# ── detect_from_seed 테스트 ───────────────────────────────────────

class TestDetectFromSeed:
    def test_own_seed_not_detected(self, detector):
        seed = _make_seed(creator="tester", freq_vec=detector.omega.copy())
        result = detector.detect_from_seed(seed)
        assert result is None

    def test_high_similarity_seed_detected(self, detector):
        # Seed frequency identical to detector omega → similarity=1.0 > delta=0.5
        seed = _make_seed(creator="other", freq_vec=detector.omega.copy())
        result = detector.detect_from_seed(seed)
        assert result is not None
        assert isinstance(result, ResonanceEvent)
        assert result.resonance_strength > 0.0

    def test_orthogonal_seed_not_detected(self, detector):
        # Build a vector orthogonal to omega
        perp = np.zeros(DIM, dtype=np.float32)
        perp[0] = 1.0
        perp -= np.dot(perp, detector.omega) * detector.omega
        perp = _unit(perp)
        seed = _make_seed(creator="other", freq_vec=perp)
        result = detector.detect_from_seed(seed)
        # cosine sim ≈ 0 < delta=0.5 → None
        assert result is None

    def test_low_energy_not_detected(self, detector):
        seed = _make_seed(creator="other", freq_vec=detector.omega.copy(), energy=0.001)
        result = detector.detect_from_seed(seed)
        assert result is None

    def test_resonance_history_appended(self, detector):
        seed = _make_seed(creator="other", freq_vec=detector.omega.copy())
        detector.detect_from_seed(seed)
        assert len(detector.resonance_history) == 1

    def test_resonance_history_capped_at_500(self, detector):
        for i in range(600):
            seed = _make_seed(seed_id=f"s{i}", creator="other",
                              freq_vec=detector.omega.copy())
            detector.detect_from_seed(seed)
        assert len(detector.resonance_history) <= 500

    def test_event_attributes(self, detector):
        seed = _make_seed(creator="other", freq_vec=detector.omega.copy())
        event = detector.detect_from_seed(seed)
        assert event.detector_id == "tester"
        assert event.seed is seed
        assert 0.0 <= event.phase_diff <= np.pi


# ── scan_field 테스트 ─────────────────────────────────────────────

class TestScanField:
    def test_no_seeds_returns_empty(self, universe, detector):
        results = detector.scan_field(universe, scan_position=3, scan_radius=5)
        assert results == []

    def test_own_seed_skipped(self, universe):
        omega = _rand_unit()
        det = ResonanceDetector("owner", omega, resonance_threshold=0.0)
        seed = _make_seed(creator="owner", freq_vec=omega.copy())
        universe.deposit_seed(seed, 3)
        results = det.scan_field(universe, scan_position=3, scan_radius=5)
        assert all(e.seed.creator_id != "owner" for e in results)

    def test_matching_seed_detected(self, universe):
        omega = _rand_unit()
        det = ResonanceDetector("scanner", omega, resonance_threshold=0.0)
        seed = _make_seed(creator="depositor", freq_vec=omega.copy())
        universe.deposit_seed(seed, 3)
        results = det.scan_field(universe, scan_position=3, scan_radius=5)
        assert len(results) >= 1

    def test_radius_filter_works(self, universe):
        omega = _rand_unit()
        det = ResonanceDetector("scanner", omega, resonance_threshold=0.0)
        seed = _make_seed(creator="far", freq_vec=omega.copy())
        universe.deposit_seed(seed, 0)            # position 0
        results = det.scan_field(universe, scan_position=7, scan_radius=1)
        # Distance = |7-0|=7 > radius=1 → not detected
        assert all(e.seed.id != seed.id for e in results)

    def test_scan_returns_resonance_events(self, universe):
        omega = _rand_unit()
        det = ResonanceDetector("sc", omega, resonance_threshold=0.0)
        seed = _make_seed(creator="dep", freq_vec=omega.copy())
        universe.deposit_seed(seed, 3)
        results = det.scan_field(universe, scan_position=3, scan_radius=5)
        for ev in results:
            assert isinstance(ev, ResonanceEvent)
            assert ev.resonance_strength >= 0.0


# ── 적응형 δ 테스트 ───────────────────────────────────────────────

class TestAdaptiveDelta:
    def test_update_adaptive_delta_is_callable(self, detector):
        detector.update_adaptive_delta([0.8, 0.9, 0.85], resonance_count=3, candidate_count=3)

    def test_high_resonance_rate_raises_delta(self, detector):
        original_delta = detector.delta
        # Force evaluation: set scan_count to trigger (multiple of 5)
        detector._scan_count = 4
        # Simulate 100% resonance rate across 10 candidates
        sims = [0.9] * 10
        detector.update_adaptive_delta(sims, resonance_count=10, candidate_count=10)
        # delta should have increased (or stayed if already at max)
        assert detector.delta >= original_delta

    def test_zero_candidates_no_change(self, detector):
        original_delta = detector.delta
        detector._scan_count = 4
        detector.update_adaptive_delta([], resonance_count=0, candidate_count=0)
        assert detector.delta == original_delta

    def test_delta_bounded_by_min_max(self, detector):
        # Drive delta to minimum
        detector._scan_count = 4
        for _ in range(20):
            detector._scan_count = 4
            detector.update_adaptive_delta(
                [0.01] * 50, resonance_count=0, candidate_count=50
            )
        assert detector.delta >= detector.delta_min

    def test_scan_count_increments(self, detector):
        before = detector._scan_count
        detector.update_adaptive_delta([0.5], resonance_count=0, candidate_count=1)
        assert detector._scan_count == before + 1
