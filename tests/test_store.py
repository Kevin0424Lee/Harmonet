"""
tests/test_store.py
===================
RedisFieldStore · FAISSSeedRegistry 단위 테스트 — CI 회귀 방지.

Redis 없이 로컬 인메모리 폴백 경로를 집중 테스트.
FAISS 있으면 FAISS 경로도 함께 테스트.
"""

import time
import numpy as np
import pytest

from harmonet.field import Seed
from harmonet.store import (
    RedisFieldStore,
    FAISSSeedRegistry,
    serialize_seed,
    deserialize_seed,
)

DIM = 16

def _rand_unit(dim: int = DIM) -> np.ndarray:
    v = np.random.randn(dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-8)

def _make_seed(seed_id="s1", creator="A", dim=DIM, freq_vec=None) -> Seed:
    return Seed(
        id=seed_id,
        creator_id=creator,
        frequency=freq_vec if freq_vec is not None else _rand_unit(dim),
        payload=_rand_unit(dim),
        rule_description="store test seed",
        energy=0.8,
        phase=1.2,
        timestamp=time.time(),
        ttl_seconds=300.0,
        metadata={"key": "value"},
    )

@pytest.fixture
def local_store():
    """Redis 없는 로컬 인메모리 스토어."""
    return RedisFieldStore(host="localhost", port=6379)

@pytest.fixture
def faiss_reg():
    return FAISSSeedRegistry(dim=DIM)


# ── serialize / deserialize 테스트 ────────────────────────────────

class TestSerialization:
    def test_roundtrip_id(self):
        s = _make_seed("roundtrip-01")
        assert deserialize_seed(serialize_seed(s)).id == s.id

    def test_roundtrip_creator(self):
        s = _make_seed(creator="creator-X")
        assert deserialize_seed(serialize_seed(s)).creator_id == "creator-X"

    def test_roundtrip_energy(self):
        s = _make_seed()
        s.energy = 0.654
        assert deserialize_seed(serialize_seed(s)).energy == pytest.approx(0.654, abs=1e-4)

    def test_roundtrip_phase(self):
        s = _make_seed()
        s.phase = 2.718
        assert deserialize_seed(serialize_seed(s)).phase == pytest.approx(2.718, abs=1e-4)

    def test_roundtrip_ttl(self):
        s = _make_seed()
        s.ttl_seconds = 120.0
        assert deserialize_seed(serialize_seed(s)).ttl_seconds == pytest.approx(120.0)

    def test_roundtrip_metadata(self):
        s = _make_seed()
        s.metadata = {"parent": "p001", "score": 0.99}
        restored = deserialize_seed(serialize_seed(s))
        assert restored.metadata["parent"] == "p001"
        assert restored.metadata["score"] == pytest.approx(0.99)

    def test_roundtrip_frequency_vector(self):
        s = _make_seed()
        restored = deserialize_seed(serialize_seed(s))
        np.testing.assert_allclose(restored.frequency, s.frequency, atol=1e-5)

    def test_roundtrip_payload_vector(self):
        s = _make_seed()
        restored = deserialize_seed(serialize_seed(s))
        np.testing.assert_allclose(restored.payload, s.payload, atol=1e-5)

    def test_roundtrip_rule_description(self):
        s = _make_seed()
        s.rule_description = "Design a REST API with OAuth2"
        assert deserialize_seed(serialize_seed(s)).rule_description == s.rule_description


# ── RedisFieldStore 로컬 폴백 테스트 ─────────────────────────────

class TestRedisFieldStoreLocal:
    def test_is_active_false_without_redis(self, local_store):
        # Redis가 없으면 is_active=False (폴백 모드)
        if local_store.is_active:
            pytest.skip("Redis is running — local fallback test skipped")
        assert local_store.is_active is False

    def test_save_field_local(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        field = np.ones((8, DIM), dtype=np.float32) * 0.5
        result = local_store.save_field(field)
        assert result is False  # local path returns False
        np.testing.assert_allclose(local_store._local_field, field)

    def test_load_field_local(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        field = np.ones((8, DIM), dtype=np.float32) * 0.3
        local_store.save_field(field)
        loaded = local_store.load_field(8, DIM)
        np.testing.assert_allclose(loaded, field)

    def test_load_field_returns_zeros_if_empty(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        result = local_store.load_field(4, DIM)
        assert result.shape == (4, DIM)
        assert np.all(result == 0.0)

    def test_deposit_seed_local(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        s = _make_seed("dep-01")
        local_store.deposit_seed(s, grid_position=3)
        assert "dep-01" in local_store._local_seeds

    def test_get_active_seeds_local(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        s = _make_seed("active-01")
        local_store.deposit_seed(s, grid_position=2)
        seeds = local_store.get_active_seeds(DIM)
        ids = [seed.id for _, seed in seeds]
        assert "active-01" in ids

    def test_remove_seed_local(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        s = _make_seed("remove-01")
        local_store.deposit_seed(s, 1)
        local_store.remove_seed("remove-01")
        assert "remove-01" not in local_store._local_seeds

    def test_claim_seed_redis_returns_true_without_redis(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        # Without Redis, always returns True (liveness first)
        result = local_store.claim_seed_redis("any-seed", "agent-X")
        assert result is True

    def test_clear_local(self, local_store):
        if local_store.is_active:
            pytest.skip("Redis running")
        s = _make_seed("clear-01")
        local_store.deposit_seed(s, 0)
        local_store.save_field(np.ones((4, DIM), dtype=np.float32))
        local_store.clear()
        assert local_store._local_field is None
        assert len(local_store._local_seeds) == 0


# ── FAISSSeedRegistry 테스트 ──────────────────────────────────────

class TestFAISSSeedRegistry:
    def test_init(self, faiss_reg):
        assert faiss_reg.dim == DIM
        assert len(faiss_reg.seeds_list) == 0

    def test_add_seed(self, faiss_reg):
        s = _make_seed("faiss-01")
        faiss_reg.add_seed(s)
        assert len(faiss_reg.seeds_list) == 1

    def test_search_empty_returns_empty(self, faiss_reg):
        q = _rand_unit()
        results = faiss_reg.search_seeds(q, top_k=5)
        assert results == []

    def test_search_returns_similar_seed(self, faiss_reg):
        omega = _rand_unit()
        s = _make_seed("match", freq_vec=omega.copy())
        faiss_reg.add_seed(s)
        results = faiss_reg.search_seeds(omega, top_k=5, min_similarity=0.0)
        assert len(results) >= 1
        assert results[0][0].id == "match"
        assert results[0][1] > 0.9  # near-identical → high score

    def test_search_top_k_limit(self, faiss_reg):
        for i in range(10):
            faiss_reg.add_seed(_make_seed(f"bulk-{i}"))
        results = faiss_reg.search_seeds(_rand_unit(), top_k=3, min_similarity=0.0)
        assert len(results) <= 3

    def test_min_similarity_filter(self, faiss_reg):
        omega = _rand_unit()
        s = _make_seed("near", freq_vec=omega.copy())
        faiss_reg.add_seed(s)
        # min_similarity=1.0 → only perfect match would pass (floating point tolerance)
        results_strict = faiss_reg.search_seeds(omega, top_k=5, min_similarity=0.99)
        assert len(results_strict) >= 1  # exact match should pass

    def test_expired_ids_filtered(self, faiss_reg):
        omega = _rand_unit()
        s = _make_seed("expired-faiss", freq_vec=omega.copy())
        faiss_reg.add_seed(s)
        results = faiss_reg.search_seeds(
            omega, top_k=5, min_similarity=0.0,
            expired_ids={"expired-faiss"}
        )
        assert all(r[0].id != "expired-faiss" for r in results)

    def test_evict_seeds_removes_from_list(self, faiss_reg):
        s1 = _make_seed("ev-1")
        s2 = _make_seed("ev-2")
        faiss_reg.add_seed(s1)
        faiss_reg.add_seed(s2)
        removed = faiss_reg.evict_seeds({"ev-1"})
        assert removed == 1
        assert all(s.id != "ev-1" for s in faiss_reg.seeds_list)

    def test_evict_seeds_rebuilds_index(self, faiss_reg):
        if not faiss_reg.is_active:
            pytest.skip("FAISS not available")
        for i in range(3):
            faiss_reg.add_seed(_make_seed(f"rb-{i}"))
        assert faiss_reg.index.ntotal == 3
        faiss_reg.evict_seeds({"rb-0"})
        assert faiss_reg.index.ntotal == 2

    def test_evict_nonexistent_no_error(self, faiss_reg):
        faiss_reg.add_seed(_make_seed("keep"))
        removed = faiss_reg.evict_seeds({"does-not-exist"})
        assert removed == 0
        assert len(faiss_reg.seeds_list) == 1

    def test_clear_resets_state(self, faiss_reg):
        for i in range(3):
            faiss_reg.add_seed(_make_seed(f"clr-{i}"))
        faiss_reg.clear()
        assert len(faiss_reg.seeds_list) == 0
        if faiss_reg.is_active:
            assert faiss_reg.index.ntotal == 0

    def test_search_results_sorted_descending(self, faiss_reg):
        omega = _rand_unit()
        # Add seeds with decreasing similarity
        faiss_reg.add_seed(_make_seed("high", freq_vec=omega.copy()))
        faiss_reg.add_seed(_make_seed("low",  freq_vec=_rand_unit()))
        results = faiss_reg.search_seeds(omega, top_k=5, min_similarity=0.0)
        if len(results) >= 2:
            assert results[0][1] >= results[1][1]

    def test_add_multiple_seeds_searchable(self, faiss_reg):
        omegas = [_rand_unit() for _ in range(5)]
        for i, ov in enumerate(omegas):
            faiss_reg.add_seed(_make_seed(f"multi-{i}", freq_vec=ov))
        assert len(faiss_reg.seeds_list) == 5
        results = faiss_reg.search_seeds(omegas[2], top_k=1, min_similarity=0.0)
        assert len(results) == 1
        assert results[0][0].id == "multi-2"
