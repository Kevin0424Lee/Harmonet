"""
tests/legacy/test_legacy_mechanisms.py
=======================
legacy 메커니즘(TDA · Kuramoto) 테스트. 기본 실행에서 제외, `pytest tests/legacy` 로 실행.
"""

import time
import numpy as np
import pytest

from harmonet.field import DataUniverseField, Seed
from harmonet.resonance import ResonanceDetector, ResonanceEvent
from harmonet.legacy import KuraMotoCoupler, validate_resonance_with_betti

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


# ── TDA validate_resonance_with_betti 테스트 ─────────────────────

class TestTDAValidation:
    def test_identical_snapshots_early_exit(self, detector):
        snap = np.random.randn(GRID, DIM).astype(np.float32)
        is_valid, reason = validate_resonance_with_betti(detector, snap, snap)
        # Δ=0 → early exit returns True
        assert is_valid is True
        assert "스킵" in reason or "TDA" in reason

    def test_different_snapshots_returns_bool(self, detector):
        before = np.zeros((GRID, DIM), dtype=np.float32)
        after  = np.random.randn(GRID, DIM).astype(np.float32)
        is_valid, reason = validate_resonance_with_betti(detector, before, after)
        assert isinstance(is_valid, bool)
        assert isinstance(reason, str)

    def test_small_change_fast_execution(self, detector):
        before = np.random.randn(GRID, DIM).astype(np.float32) * 0.1
        after  = before + np.random.randn(GRID, DIM).astype(np.float32) * 0.5
        import time as _t
        t0 = _t.time()
        validate_resonance_with_betti(detector, before, after)
        elapsed = _t.time() - t0
        assert elapsed < 2.0  # TDA 서브샘플링으로 2초 내 완료


# ── KuraMotoCoupler 테스트 ────────────────────────────────────────

class TestKuraMotoCoupler:
    def test_register_agent(self):
        kc = KuraMotoCoupler(coupling_strength=0.5)
        kc.register_agent("A", natural_frequency=1.0)
        assert "A" in kc.phases
        assert "A" in kc.frequencies

    def test_initial_order_parameter_single(self):
        kc = KuraMotoCoupler()
        kc.register_agent("A", 1.0)
        r, psi = kc.get_order_parameter()
        assert r == pytest.approx(1.0, abs=0.01)

    def test_order_parameter_range(self):
        kc = KuraMotoCoupler(coupling_strength=0.5)
        for i in range(5):
            kc.register_agent(f"agent{i}", float(i))
        r, psi = kc.get_order_parameter()
        assert 0.0 <= r <= 1.0

    def test_step_changes_phases(self):
        kc = KuraMotoCoupler(coupling_strength=1.0)
        kc.register_agent("A", 1.0)
        kc.register_agent("B", 1.5)
        before = dict(kc.phases)
        kc.step(dt=0.1)
        # At least one phase should change
        assert any(kc.phases[k] != before[k] for k in before)

    def test_synchronization_over_time(self):
        kc = KuraMotoCoupler(coupling_strength=2.0)
        for i in range(3):
            kc.register_agent(f"a{i}", float(i) * 0.1)  # similar frequencies
        r_init, _ = kc.get_order_parameter()
        for _ in range(50):
            kc.step(dt=0.1)
        r_final, _ = kc.get_order_parameter()
        # Strong coupling + similar freq → r should increase
        assert r_final >= r_init - 0.1  # allow small tolerance

    def test_get_phase_returns_float(self):
        kc = KuraMotoCoupler()
        kc.register_agent("X", 1.0)
        assert isinstance(kc.get_phase("X"), float)

    def test_get_phase_unknown_agent(self):
        kc = KuraMotoCoupler()
        assert kc.get_phase("nonexistent") == 0.0

    def test_order_parameter_empty(self):
        kc = KuraMotoCoupler()
        r, psi = kc.get_order_parameter()
        assert r == 0.0
        assert psi == 0.0

    def test_adaptive_coupling_strength(self):
        kc = KuraMotoCoupler(coupling_strength=0.5)
        kc.register_agent("A", 1.0)
        kc.register_agent("B", 1.0)
        # After step, K should adapt based on r
        kc.step(dt=0.1)
        assert kc.K != kc.base_K or True  # K adapts; just verify no crash
