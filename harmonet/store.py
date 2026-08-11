"""
HarmoNet Distributed Store Layer
================================
Redis를 통한 멀티프로세스 필드 동기화 및 FAISS를 이용한 O(log N) 시맨틱 검색 인덱스를 구현합니다.
Redis/FAISS 서버가 부재하거나 라이브러리가 없는 경우를 대비해 Local Memory/Brute-force 폴백을 제공합니다.
"""

import numpy as np
import base64
import json
import os
import time
from typing import Dict, List, Optional, Tuple, Any
from .field import Seed

# FAISS 라이브러리 로드 시도
try:
    import faiss
    _faiss_available = True
except ImportError:
    _faiss_available = False

# Redis 라이브러리 로드 시도
try:
    import redis
    _redis_available = True
except ImportError:
    _redis_available = False


def serialize_seed(seed: Seed) -> str:
    """Seed 객체를 JSON 문자열로 직렬화 (numpy 배열은 base64 인코딩)"""
    return json.dumps({
        "id": seed.id,
        "creator_id": seed.creator_id,
        "frequency": base64.b64encode(seed.frequency.astype(np.float32).tobytes()).decode("utf-8"),
        "payload": base64.b64encode(seed.payload.astype(np.float32).tobytes()).decode("utf-8"),
        "rule_description": seed.rule_description,
        "energy": seed.energy,
        "phase": seed.phase,
        "timestamp": seed.timestamp,
        "ttl_seconds": seed.ttl_seconds,   # ← 누락되었던 필드: Redis 왕복 후에도 TTL 보존
        "metadata": seed.metadata
    })


def deserialize_seed(serialized: str) -> Seed:
    """JSON 문자열로부터 Seed 객체 역직렬화"""
    d = json.loads(serialized)
    freq_bytes = base64.b64decode(d["frequency"].encode("utf-8"))
    payload_bytes = base64.b64decode(d["payload"].encode("utf-8"))

    freq = np.frombuffer(freq_bytes, dtype=np.float32)
    payload = np.frombuffer(payload_bytes, dtype=np.float32)

    return Seed(
        id=d["id"],
        creator_id=d["creator_id"],
        frequency=freq,
        payload=payload,
        rule_description=d["rule_description"],
        energy=d["energy"],
        phase=d["phase"],
        timestamp=d["timestamp"],
        ttl_seconds=d.get("ttl_seconds", 300.0),  # 구버전 데이터 호환 폴백
        metadata=d["metadata"]
    )


class RedisFieldStore:
    """Redis 기반 공유 필드 및 시드 공유 저장소 (멀티프로세스 동기화용)"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 6379, db: int = 0, key_prefix: str = "harmo"):
        self.host = os.getenv("HARMONET_REDIS_HOST", host)
        self.port = int(os.getenv("HARMONET_REDIS_PORT", str(port)))
        self.db = db
        self.prefix = key_prefix
        self.client = None
        self.is_active = False

        if os.getenv("HARMONET_DISABLE_REDIS", "").lower() in {"1", "true", "yes"}:
            print("[RedisStore] HARMONET_DISABLE_REDIS 설정됨. 로컬 인메모리 대체 모드를 사용합니다.")
            self._local_field: Optional[np.ndarray] = None
            self._local_seeds: Dict[str, Tuple[int, Seed]] = {}
            return
        
        if _redis_available:
            try:
                connect_timeout = float(os.getenv("HARMONET_REDIS_CONNECT_TIMEOUT", "0.2"))
                socket_timeout = float(os.getenv("HARMONET_REDIS_SOCKET_TIMEOUT", "0.2"))
                redis_kwargs = {}
                try:
                    from redis.retry import Retry
                    from redis.backoff import NoBackoff
                    redis_kwargs["retry"] = Retry(NoBackoff(), 0)
                except Exception:
                    pass
                # 짧은 타임아웃 설정으로 Redis 오프라인 시 빠른 폴백 전환 유도
                self.client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=db,
                    socket_connect_timeout=connect_timeout,
                    socket_timeout=socket_timeout,
                    health_check_interval=0,
                    **redis_kwargs,
                )
                # 연결 테스트
                self.client.ping()
                self.is_active = True
                print(f"[RedisStore] Redis 서버가 감지되었습니다. 분산 저장소를 활성화합니다 ({self.host}:{self.port}).")
            except Exception as e:
                print(f"[RedisStore] Redis 서버 연결 실패 ({str(e)}). 로컬 인메모리 대체 모드를 사용합니다.")
        else:
            print("[RedisStore] redis-py 라이브러리가 존재하지 않습니다. 로컬 인메모리 대체 모드를 사용합니다.")
            
        # 로컬 폴백용 스토리지
        self._local_field: Optional[np.ndarray] = None
        self._local_seeds: Dict[str, Tuple[int, Seed]] = {}

    def save_field(self, field_array: np.ndarray) -> bool:
        """벡터 필드 전체 상태를 저장"""
        if self.is_active and self.client:
            try:
                # 필드를 바이너리 바이트로 변환 후 저장
                shape_str = f"{field_array.shape[0]},{field_array.shape[1]}"
                self.client.set(f"{self.prefix}:field:data", field_array.astype(np.float32).tobytes())
                self.client.set(f"{self.prefix}:field:shape", shape_str)
                return True
            except Exception as e:
                print(f"[RedisStore] save_field 에러: {str(e)}, 로컬 폴백 수행.")
                
        self._local_field = field_array.copy()
        return False

    def load_field(self, grid_size: int, dim: int) -> np.ndarray:
        """벡터 필드 전체 상태를 로드"""
        if self.is_active and self.client:
            try:
                data_bytes = self.client.get(f"{self.prefix}:field:data")
                shape_str = self.client.get(f"{self.prefix}:field:shape")
                
                if data_bytes and shape_str:
                    shape = tuple(map(int, shape_str.decode("utf-8").split(",")))
                    arr = np.frombuffer(data_bytes, dtype=np.float32).reshape(shape)
                    return arr.copy()
            except Exception as e:
                print(f"[RedisStore] load_field 에러: {str(e)}, 로컬 폴백 수행.")
                
        if self._local_field is not None:
            return self._local_field.copy()
            
        return np.zeros((grid_size, dim), dtype=np.float32)

    def deposit_seed(self, seed: Seed, grid_position: int) -> bool:
        """씨앗과 해당 위치를 저장소에 등록"""
        serialized = serialize_seed(seed)
        if self.is_active and self.client:
            try:
                # Hash 형태로 씨앗 정보 저장 {seed_id: serialized_seed}
                self.client.hset(f"{self.prefix}:seeds:registry", seed.id, serialized)
                # 위치 정보 해시맵 저장 {seed_id: position}
                self.client.hset(f"{self.prefix}:seeds:positions", seed.id, grid_position)
                return True
            except Exception as e:
                print(f"[RedisStore] deposit_seed 에러: {str(e)}, 로컬 폴백 수행.")
                
        self._local_seeds[seed.id] = (grid_position, seed)
        return False

    def get_active_seeds(self, dim: int) -> List[Tuple[int, Seed]]:
        """저장된 모든 활성 씨앗 리스트를 가져옴"""
        if self.is_active and self.client:
            try:
                registry = self.client.hgetall(f"{self.prefix}:seeds:registry")
                positions = self.client.hgetall(f"{self.prefix}:seeds:positions")
                
                active_seeds = []
                for seed_id_bytes, val_bytes in registry.items():
                    seed_id = seed_id_bytes.decode("utf-8")
                    seed = deserialize_seed(val_bytes.decode("utf-8"))
                    pos = int(positions.get(seed_id_bytes, b"0").decode("utf-8"))
                    active_seeds.append((pos, seed))
                return active_seeds
            except Exception as e:
                print(f"[RedisStore] get_active_seeds 에러: {str(e)}, 로컬 폴백 수행.")
                
        return list(self._local_seeds.values())

    def remove_seed(self, seed_id: str) -> None:
        """
        씨앗을 Redis(또는 로컬 폴백)에서 완전 제거.
        TTL 만료 씨앗이 Redis hash에 영구 누적되는 메모리 누수를 차단합니다.
        """
        if self.is_active and self.client:
            try:
                self.client.hdel(f"{self.prefix}:seeds:registry", seed_id)
                self.client.hdel(f"{self.prefix}:seeds:positions", seed_id)
            except Exception as e:
                print(f"[RedisStore] remove_seed 에러: {str(e)}")
        self._local_seeds.pop(seed_id, None)

    def claim_seed_redis(self, seed_id: str, agent_id: str, ttl_sec: int = 120) -> bool:
        """
        Redis SETNX로 씨앗 처리권 원자적 선점 (멀티프로세스 분산 잠금).

        SET key value NX EX ttl_sec:
          - NX  : key가 없을 때만 SET (원자적 선점)
          - EX  : TTL 초과 시 자동 만료 (데드락 방지)

        Returns:
            True  — 선점 성공
            False — 다른 프로세스가 이미 선점
        """
        if not self.is_active or not self.client:
            return True  # Redis 없을 때는 in-process 잠금으로 위임
        key = f"{self.prefix}:claim:{seed_id}"
        try:
            result = self.client.set(key, agent_id, nx=True, ex=ttl_sec)
            return result is True
        except Exception as e:
            print(f"[RedisStore] claim_seed_redis 에러: {str(e)}, 처리 허용.")
            return True  # 에러 시 안전하게 허용 (liveness 우선)

    def clear(self) -> None:
        """스토어 초기화"""
        if self.is_active and self.client:
            try:
                keys = self.client.keys(f"{self.prefix}:*")
                if keys:
                    self.client.delete(*keys)
                print("[RedisStore] Redis HarmoNet 네임스페이스가 초기화되었습니다.")
            except Exception as e:
                print(f"[RedisStore] clear 에러: {str(e)}")

        self._local_field = None
        self._local_seeds.clear()


class FAISSSeedRegistry:
    """FAISS 기반 고속 벡터 검색 씨앗 레지스트리 (O(log N) 탐색용)"""
    
    def __init__(self, dim: int):
        self.dim = dim
        self.index = None
        self.seeds_list: List[Seed] = []
        self.is_active = False
        
        if _faiss_available:
            try:
                # Cosine 유사도는 정규화된 벡터의 Inner Product(IP)와 동일하므로 IndexFlatIP 사용
                self.index = faiss.IndexFlatIP(dim)
                self.is_active = True
                print(f"[FAISSStore] FAISS FlatIP 인덱스가 활성화되었습니다 (차원={dim}).")
            except Exception as e:
                print(f"[FAISSStore] FAISS 초기화 에러 ({str(e)}). 로컬 브루트포스 검색으로 전환합니다.")
        else:
            print("[FAISSStore] faiss-cpu 라이브러리가 존재하지 않습니다. 로컬 브루트포스 검색으로 전환합니다.")

    def add_seed(self, seed: Seed) -> None:
        """씨앗을 FAISS 인덱스에 등록"""
        self.seeds_list.append(seed)
        
        if self.is_active and self.index:
            try:
                # 주파수 벡터 추출 및 float32 정규화
                freq_vec = seed.frequency.astype(np.float32)
                norm = np.linalg.norm(freq_vec)
                if norm > 1e-8:
                    freq_vec = freq_vec / norm
                
                # FAISS 인덱스에 벡터 추가 (1, dim) 모양
                self.index.add(freq_vec.reshape(1, -1))
            except Exception as e:
                print(f"[FAISSStore] add_seed 에러: {str(e)}, 폴백 모드로 등록.")

    def search_seeds(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        min_similarity: float = 0.0,
        expired_ids: Optional[set] = None,
    ) -> List[Tuple[Seed, float]]:
        """
        도메인 쿼리 벡터와 유사한 씨앗을 고속 검색.

        expired_ids: 호출자가 넘겨준 TTL 만료 씨앗 ID set.
                     FAISS 인덱스는 삭제를 지원하지 않으므로 soft-delete로 처리.
        """
        if not self.seeds_list:
            return []
        if expired_ids is None:
            expired_ids = set()
            
        # 쿼리 벡터 L2 정규화
        q_vec = query_vector.astype(np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 1e-8:
            q_vec = q_vec / q_norm
            
        # 1. FAISS 활성화 모드 검색
        if self.is_active and self.index and self.index.ntotal > 0:
            try:
                k = min(top_k, self.index.ntotal)
                # D: 유사도 점수 (Inner Product), I: 인덱스 번호
                D, I = self.index.search(q_vec.reshape(1, -1), k)
                
                results = []
                for idx, score in zip(I[0], D[0]):
                    if idx < 0 or idx >= len(self.seeds_list):
                        continue
                    seed = self.seeds_list[idx]
                    if seed.id in expired_ids:
                        continue  # soft-delete: TTL 만료 씨앗 제외
                    if score >= min_similarity:
                        results.append((seed, float(score)))
                return results
            except Exception as e:
                print(f"[FAISSStore] search_seeds 에러: {str(e)}, 브루트포스 검색을 수행합니다.")

        # 2. 로컬 브루트포스 폴백 검색 (Numpy)
        results = []
        for seed in self.seeds_list:
            if seed.id in expired_ids:
                continue  # soft-delete
            s_vec = seed.frequency.astype(np.float32)
            s_norm = np.linalg.norm(s_vec)
            if s_norm > 1e-8:
                s_vec = s_vec / s_norm

            similarity = float(np.dot(q_vec, s_vec))
            if similarity >= min_similarity:
                results.append((seed, similarity))
                
        # 유사도 내림차순 정렬 후 상위 top_k 반환
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def evict_seeds(self, expired_ids: set) -> int:
        """
        만료 씨앗을 seeds_list에서 완전 제거 후 FAISS 인덱스 리빌드 (hard-delete).

        FAISS IndexFlatIP는 개별 벡터 삭제를 지원하지 않으므로
        남은 씨앗만으로 인덱스를 처음부터 재구성합니다.
        384-dim × 수백 씨앗 기준 리빌드는 ~1ms 이내로 매우 빠릅니다.

        Returns:
            제거된 씨앗 수
        """
        if not expired_ids:
            return 0

        before = len(self.seeds_list)
        self.seeds_list = [s for s in self.seeds_list if s.id not in expired_ids]
        removed = before - len(self.seeds_list)

        if removed > 0:
            self._rebuild_index()
            print(f"[FAISSStore] ♻  {removed}개 씨앗 hard-delete 후 인덱스 리빌드 "
                  f"(잔여={len(self.seeds_list)}, ntotal={self.index.ntotal if self.index else 0})")
        return removed

    def _rebuild_index(self) -> None:
        """
        남은 seeds_list 전체로 FAISS 인덱스를 재구성.
        index.reset() 후 남은 씨앗의 주파수 벡터를 일괄 add.
        """
        if not self.is_active or not self.index:
            return
        try:
            self.index.reset()
            if not self.seeds_list:
                return
            # 남은 씨앗의 정규화된 주파수 벡터를 배치로 add
            vecs = []
            for seed in self.seeds_list:
                fv = seed.frequency.astype(np.float32)
                norm = np.linalg.norm(fv)
                vecs.append(fv / (norm + 1e-8) if norm > 1e-8 else fv)
            batch = np.stack(vecs, axis=0)   # (N, dim)
            self.index.add(batch)
        except Exception as e:
            print(f"[FAISSStore] _rebuild_index 에러: {str(e)}")

    def clear(self) -> None:
        """인덱스 초기화"""
        self.seeds_list.clear()
        if self.is_active and self.index:
            try:
                self.index.reset()
            except Exception as e:
                print(f"[FAISSStore] clear 에러: {str(e)}")
