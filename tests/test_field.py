"""
tests/test_field.py
===================
DataUniverseField 단위 테스트 — CI 회귀 방지.

- Redis 없이도 동작 (로컬 폴백 모드)
- 임베딩 모델 없이도 동작 (numpy 벡터 직접 생성)
- dim=16, grid_size=8 소형 우주로 빠른 실행
"""

import time
import numpy as np
import pytest

from harmonet.field import DataUniverseField, Seed


# ── 공통 픽스처 ──────────────────────────────────────────────────

DIM  = 16
GRID = 8

def _rand_unit(dim: int = DIM) -> np.ndarray:
    v = np.random.randn(dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-8)

def _make_seed(
    seed_id: str = "seed-001",
    creator_id: str = "agent-A",
    energy: float = 0.8,
    ttl: float = 300.0,
    timestamp: float | None = None,
    dim: int = DIM,
) -> Seed:
    return Seed(
        id=seed_id,
        creator_id=creator_id,
        frequency=_rand_unit(dim),
        payload=_rand_unit(dim),
        rule_description="Unit test seed",
        energy=energy,
        phase=1.0,
        timestamp=timestamp if timestamp is not None else time.time(),
        ttl_seconds=ttl,
    )

@pytest.fixture
def universe():
    return DataUniverseField(dim=DIM, grid_size=GRID)

@pytest.fixture
def seed_a():
    return _make_seed("seed-A", "agent-A")

@pytest.fixture
def seed_b():
    return _make_seed("seed-B", "agent-B")


# ── 초기화 테스트 ─────────────────────────────────────────────────

class TestInit:
    def test_field_shape(self, universe):
        assert universe.field.shape == (GRID, DIM)

    def test_field_starts_zero(self, universe):
        assert np.all(universe.field == 0.0)

    def test_registry_empty(self, universe):
        assert len(universe.seed_registry) == 0

    def test_tick_zero(self, universe):
        assert universe._tick == 0

    def test_physical_constants(self):
        assert DataUniverseField.G_DATA == 0.05
        assert DataUniverseField.C_DATA == 1.0
        assert DataUniverseField.H_DATA == 0.01


# ── deposit_seed 테스트 ───────────────────────────────────────────

class TestDepositSeed:
    def test_seed_registered(self, universe, seed_a):
        universe.deposit_seed(seed_a, grid_position=3)
        assert seed_a.id in universe.seed_registry

    def test_seed_position_stored(self, universe, seed_a):
        universe.deposit_seed(seed_a, grid_position=3)
        pos, _ = universe.seed_registry[seed_a.id]
        assert pos == 3

    def test_field_perturbed_at_deposit_position(self, universe, seed_a):
        universe.deposit_seed(seed_a, grid_position=3)
        assert np.linalg.norm(universe.field[3]) > 0.0

    def test_gaussian_smearing_affects_neighbours(self, universe, seed_a):
        universe.deposit_seed(seed_a, grid_position=4)
        # Positions 3 and 5 (within offset range ±2) should also be non-zero
        assert np.linalg.norm(universe.field[3]) > 0.0
        assert np.linalg.norm(universe.field[5]) > 0.0

    def test_low_energy_seed_rejected(self, universe):
        bad_seed = _make_seed(energy=0.001)  # below H_DATA threshold
        universe.deposit_seed(bad_seed, grid_position=0)
        assert bad_seed.id not in universe.seed_registry

    def test_multiple_seeds_accumulate(self, universe, seed_a, seed_b):
        universe.deposit_seed(seed_a, grid_position=1)
        universe.deposit_seed(seed_b, grid_position=2)
        assert len(universe.seed_registry) == 2

    def test_faiss_index_updated(self, universe, seed_a):
        universe.deposit_seed(seed_a, grid_position=2)
        if universe.faiss_registry.is_active:
            assert universe.faiss_registry.index.ntotal == 1

    def test_energy_in_field_proportional_to_seed_energy(self, universe):
        high = _make_seed("h", energy=1.0)
        low  = _make_seed("l", energy=0.3)
        u_high = DataUniverseField(dim=DIM, grid_size=GRID)
        u_low  = DataUniverseField(dim=DIM, grid_size=GRID)
        # Use identical frequency/payload so only energy differs
        high.frequency = low.frequency = _rand_unit()
        high.payload   = low.payload   = _rand_unit()
        u_high.deposit_seed(high, 4)
        u_low.deposit_seed(low,  4)
        assert u_high.get_global_energy() > u_low.get_global_energy()


# ── claim_seed 테스트 ─────────────────────────────────────────────

class TestClaimSeed:
    def test_first_claim_succeeds(self, universe, seed_a):
        universe.deposit_seed(seed_a, 0)
        assert universe.claim_seed(seed_a.id, "agent-A") is True

    def test_second_claim_fails(self, universe, seed_a):
        universe.deposit_seed(seed_a, 0)
        universe.claim_seed(seed_a.id, "agent-A")
        assert universe.claim_seed(seed_a.id, "agent-B") is False

    def test_different_seeds_independent(self, universe, seed_a, seed_b):
        universe.deposit_seed(seed_a, 0)
        universe.deposit_seed(seed_b, 1)
        assert universe.claim_seed(seed_a.id, "agent-A") is True
        assert universe.claim_seed(seed_b.id, "agent-B") is True

    def test_unknown_seed_claim_without_redis(self, universe):
        # seed not in registry — local path returns True (liveness 우선)
        assert universe.claim_seed("nonexistent-seed", "agent-X") is True


# ── evict_expired_seeds 테스트 ────────────────────────────────────

class TestEvictExpiredSeeds:
    def test_expired_seed_removed(self, universe):
        expired = _make_seed(seed_id="expired", timestamp=time.time() - 400, ttl=300.0)
        universe.seed_registry[expired.id] = (0, expired)
        removed = universe.evict_expired_seeds()
        assert removed == 1
        assert "expired" not in universe.seed_registry

    def test_fresh_seed_not_removed(self, universe, seed_a):
        universe.deposit_seed(seed_a, 0)
        removed = universe.evict_expired_seeds()
        assert removed == 0
        assert seed_a.id in universe.seed_registry

    def test_mixed_seeds(self, universe, seed_a):
        expired = _make_seed(seed_id="exp2", timestamp=time.time() - 1000, ttl=300.0)
        universe.deposit_seed(seed_a, 0)
        universe.seed_registry[expired.id] = (1, expired)
        removed = universe.evict_expired_seeds()
        assert removed == 1
        assert seed_a.id in universe.seed_registry
        assert expired.id not in universe.seed_registry

    def test_claimed_seeds_cleaned_up(self, universe):
        expired = _make_seed(seed_id="exp3", timestamp=time.time() - 400, ttl=300.0)
        universe.seed_registry[expired.id] = (0, expired)
        universe._claimed_seeds[expired.id] = "agent-X"
        universe.evict_expired_seeds()
        assert expired.id not in universe._claimed_seeds


# ── propagate 테스트 ──────────────────────────────────────────────

class TestPropagate:
    def test_propagate_changes_field(self, universe, seed_a):
        universe.deposit_seed(seed_a, 3)
        before = universe.field.copy()
        universe.propagate(dt=0.5)
        assert not np.allclose(universe.field, before)

    def test_tick_increments(self, universe):
        assert universe._tick == 0
        universe.propagate()
        assert universe._tick == 1
        universe.propagate()
        assert universe._tick == 2

    def test_field_clips_to_bounds(self, universe):
        # Inject artificially large values
        universe.field[:] = 100.0
        universe.propagate(dt=1.0)
        assert np.all(universe.field <= 10.0)
        assert np.all(universe.field >= -10.0)

    def test_energy_decays_without_new_seeds(self, universe, seed_a):
        universe.deposit_seed(seed_a, 3)
        e0 = universe.get_global_energy()
        for _ in range(10):
            universe.propagate(dt=0.5)
        assert universe.get_global_energy() < e0

    def test_snapshot_stored_at_interval(self, universe, seed_a):
        universe.deposit_seed(seed_a, 3)
        interval = universe.snapshot_interval
        for _ in range(interval):
            universe.propagate(dt=0.5)
        assert len(universe.field_snapshots) >= 1

    def test_snapshot_capped_at_20(self, universe, seed_a):
        universe.deposit_seed(seed_a, 3)
        for _ in range(universe.snapshot_interval * 25):
            universe.propagate(dt=0.1)
        assert len(universe.field_snapshots) <= 20


# ── get_field_at / density_gradient 테스트 ───────────────────────

class TestFieldQuery:
    def test_get_field_at_returns_correct_shape(self, universe, seed_a):
        universe.deposit_seed(seed_a, 2)
        vec = universe.get_field_at(2)
        assert vec.shape == (DIM,)

    def test_get_global_energy_zero_initially(self, universe):
        assert universe.get_global_energy() == pytest.approx(0.0, abs=1e-6)

    def test_get_global_energy_positive_after_deposit(self, universe, seed_a):
        universe.deposit_seed(seed_a, 3)
        assert universe.get_global_energy() > 0.0

    def test_density_gradient_shape(self, universe, seed_a):
        universe.deposit_seed(seed_a, 3)
        grad = universe.get_density_gradient(3)
        assert grad.shape == (DIM,)

    def test_get_active_seeds_returns_deposited(self, universe, seed_a):
        universe.deposit_seed(seed_a, 3)
        active = universe.get_active_seeds(min_energy_threshold=0.0)
        ids = [s.id for _, s in active]
        assert seed_a.id in ids


# ── sync_seed_registry_from_store 테스트 ─────────────────────────

class TestSyncSeedRegistry:
    def test_no_redis_returns_zero(self, universe):
        # In CI / no-Redis env, should return 0 safely
        result = universe.sync_seed_registry_from_store()
        assert result == 0

    def test_already_known_seeds_not_counted(self, universe, seed_a):
        universe.deposit_seed(seed_a, 2)
        # Manually add to local store fallback to simulate "remote" seed
        universe.store._local_seeds[seed_a.id] = (2, seed_a)
        result = universe.sync_seed_registry_from_store()
        # Already in registry, so 0 new
        assert result == 0
