"""
DataUniverseField: 공유 데이터 우주 벡터 공간
================================================
QFT 장 교란 + 스티그머지 확산 방정식 구현.

물리 모델 대응:
- 배경 공간 η_μν      → self.field (초기 zero 벡터)
- 에이전트 교란 h_μν  → deposit_seed()
- 페로몬 확산 방정식  → propagate()
- 데이터 우주 물리 상수 G, c, ħ → 에이전트 인력, 전파 속도, 최소 단위
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import time


@dataclass
class Seed:
    """
    씨앗 수식 (Seed Formula).
    Kolmogorov 최적 프로그램의 근사:
    전체 맥락을 재생성할 수 있는 최단 생성 규칙.
    """
    id: str                          # 씨앗 고유 ID
    creator_id: str                  # 생성한 에이전트 ID
    frequency: np.ndarray            # 씨앗의 '주파수' (도메인 특성 벡터)
    payload: np.ndarray              # 압축된 씨앗 벡터 (정보 본체)
    rule_description: str            # 인간 가독형 규칙 설명 (디버그/감사용)
    energy: float = 1.0              # 씨앗의 에너지 (장에 미치는 교란 강도)
    phase: float = 0.0               # 생성 시점의 에이전트 위상
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: float = 300.0       # 생존 시간 (기본 5분, 이후 자동 만료)
    metadata: Dict = field(default_factory=dict)

    def to_field_vector(self) -> np.ndarray:
        """씨앗을 벡터 필드에 투하할 수 있는 교란 벡터로 변환"""
        return self.payload * self.energy

    def __repr__(self):
        return (f"Seed(id={self.id[:8]}..., creator={self.creator_id}, "
                f"energy={self.energy:.2f}, rule='{self.rule_description[:50]}...')")


class DataUniverseField:
    """
    데이터 우주 벡터 필드.
    
    에이전트들이 직접 메시지 없이 이 공간의 '상태 변화'만으로 협업.
    
    수학적 모델:
    - 필드 업데이트: ∂φ/∂t = D·∇²φ - ρ·φ + S(x,t)
      - D   = diffusion_rate  (정보 확산 속도)
      - ρ   = decay_rate      (오래된 신호 증발율)
      - S   = 에이전트의 씨앗 투하 (소스 항)
    
    물리 상수 (데이터 우주의 하이퍼파라미터):
    - G_data: 에이전트 간 인력 상수 (유사 에이전트 클러스터링 경향)
    - c_data: 정보 전파 속도 상한
    - h_data: 정보 교환의 최소 단위 (최소 씨앗 에너지)
    """

    # ─── 데이터 우주 물리 상수 ───────────────────────────────────
    G_DATA = 0.05    # 에이전트 인력 상수 (중력 아날로그)
    C_DATA = 1.0     # 정보 전파 속도 상한 (광속 아날로그)
    H_DATA = 0.01    # 최소 정보 교환 단위 (플랑크 상수 아날로그)

    def __init__(
        self,
        dim: int = 256,
        grid_size: int = 32,
        decay_rate: float = 0.02,
        diffusion_rate: float = 0.05,
    ):
        """
        Args:
            dim:            벡터 차원 수 (데이터 우주의 공간 차원)
            grid_size:      그리드 크기 (에이전트 위치 공간)
            decay_rate:     신호 감쇠율 ρ (스티그머지 페로몬 증발)
            diffusion_rate: 확산 계수 D (정보 전파율)
        """
        self.dim = dim
        self.grid_size = grid_size
        self.decay_rate = decay_rate
        self.diffusion_rate = diffusion_rate

        # 배경 필드 η_μν (초기 상태 = 평탄한 데이터 우주)
        self.field = np.zeros((grid_size, dim), dtype=np.float32)

        # 투하된 씨앗들의 레지스트리 {seed_id: (grid_pos, Seed)}
        self.seed_registry: Dict[str, Tuple[int, Seed]] = {}

        # 씨앗 처리권 선점 테이블 {seed_id: agent_id} — 동일 프로세스 내 race condition 방지
        self._claimed_seeds: Dict[str, str] = {}

        # 필드 변화 히스토리 (TDA 분석용)
        self.field_snapshots: List[np.ndarray] = []
        self.snapshot_interval = 5  # N번 업데이트마다 스냅샷 저장
        self._tick = 0

        # 분산 필드 스토어 및 FAISS 세션 등록
        from .store import RedisFieldStore, FAISSSeedRegistry
        self.store = RedisFieldStore()
        self.faiss_registry = FAISSSeedRegistry(dim=dim)

        # Redis가 활성화되어 있으면 기존에 저장된 상태 로드
        if self.store.is_active:
            self.field = self.store.load_field(grid_size, dim)

        print(f"[DataUniverse] 초기화 완료: dim={dim}, grid={grid_size}x{dim}")
        print(f"[DataUniverse] 물리 상수: G={self.G_DATA}, c={self.C_DATA}, ħ={self.H_DATA}")

    # ─── 씨앗 투하 (에이전트의 장 교란) ─────────────────────────

    def deposit_seed(self, seed: Seed, grid_position: int) -> None:
        """
        에이전트가 씨앗을 데이터 우주에 투하.
        QFT 장 교란: φ(x) → φ(x) + δφ_agent(x)
        
        Args:
            seed:          투하할 씨앗 수식
            grid_position: 투하 위치 (0 ~ grid_size-1)
        """
        # NaN/Inf 벡터는 필드 전체를 오염시키므로 거부 (조용히 더하지 않는다 — WEEK1 A2)
        if not (np.all(np.isfinite(seed.frequency)) and np.all(np.isfinite(seed.payload))):
            raise ValueError(f"[DataUniverse] 씨앗 {seed.id[:8]} 벡터에 NaN/Inf 가 있습니다. 투하 거부.")
        # 에너지가 최소 단위(ħ) 이상인지 검증
        if seed.energy < self.H_DATA:
            print(f"[DataUniverse] ⚠ 씨앗 에너지({seed.energy:.4f}) < ħ({self.H_DATA}). 투하 거부.")
            return

        # 장 교란 적용 (가우시안 스미어링으로 주변으로 퍼짐)
        perturbation = seed.to_field_vector()
        for offset in range(-2, 3):
            pos = (grid_position + offset) % self.grid_size
            distance_weight = np.exp(-0.5 * (offset ** 2))  # 가우시안 감쇠
            self.field[pos] += perturbation * distance_weight

        # 로컬 레지스트리에 등록
        self.seed_registry[seed.id] = (grid_position, seed)

        # Redis 분산 필드 연동
        self.store.deposit_seed(seed, grid_position)
        self.store.save_field(self.field)

        # FAISS 고속 시맨틱 인덱스 연동
        self.faiss_registry.add_seed(seed)

        print(f"[DataUniverse] 🌱 씨앗 투하: {seed.creator_id} → 위치[{grid_position}] "
              f"에너지={seed.energy:.2f} | '{seed.rule_description[:40]}'")

    # ─── 분산 씨앗 레지스트리 동기화 ───────────────────────────────

    def sync_seed_registry_from_store(self) -> int:
        """
        Redis에서 타 프로세스가 투하한 씨앗을 로컬 seed_registry·FAISS로 동기화.

        멀티프로세스 분산 배포 시나리오:
        - 프로세스 A가 deposit_seed() → Redis에 저장
        - 프로세스 B의 seed_registry는 A의 씨앗을 모름
        - 이 메서드를 propagate() 초반에 호출하면 B도 A의 씨앗을 인식하게 됨
        - scan_field() FAISS 경로가 cross-process 씨앗도 탐지 가능해짐

        Returns:
            새로 동기화된 씨앗 수 (이미 알고 있는 씨앗은 제외)
        """
        if not self.store.is_active:
            return 0

        try:
            remote_seeds = self.store.get_active_seeds(self.dim)
        except Exception as e:
            print(f"[DataUniverse] sync_seed_registry_from_store 에러: {e}")
            return 0

        new_count = 0
        for pos, seed in remote_seeds:
            if seed.id not in self.seed_registry:
                self.seed_registry[seed.id] = (pos, seed)
                # 로컬 FAISS 인덱스에도 등록 (cross-process 씨앗 고속 검색 지원)
                self.faiss_registry.add_seed(seed)
                new_count += 1

        if new_count > 0:
            print(f"[DataUniverse] 🔄 분산 동기화: "
                  f"{new_count}개 씨앗 외부 프로세스로부터 수신 "
                  f"(총 레지스트리={len(self.seed_registry)}개)")
        return new_count

    # ─── 씨앗 선점 & TTL 관리 ────────────────────────────────────

    def claim_seed(self, seed_id: str, agent_id: str) -> bool:
        """
        씨앗 처리권 원자적 선점.

        1순위: Redis SETNX — 멀티프로세스 환경에서 분산 잠금
        2순위: 인-프로세스 딕셔너리 — 단일 프로세스 asyncio 병렬 환경

        Returns:
            True  — 선점 성공 (이 에이전트가 처리해야 함)
            False — 이미 다른 에이전트가 선점 (처리 스킵)
        """
        # Redis 분산 잠금 (멀티프로세스)
        if self.store.is_active:
            return self.store.claim_seed_redis(seed_id, agent_id, ttl_sec=120)

        # 인-프로세스 원자적 선점 (asyncio는 단일 스레드이므로 dict 삽입이 원자적)
        if seed_id in self._claimed_seeds:
            return False
        self._claimed_seeds[seed_id] = agent_id
        return True

    def evict_expired_seeds(self) -> int:
        """
        TTL 초과 씨앗을 레지스트리와 선점 테이블에서 제거.

        - seed_registry에서 삭제 → 이후 scan_field에서 감지되지 않음
        - _claimed_seeds에서도 함께 정리 → 만료 씨앗의 클레임이 딕셔너리를 점유하지 않음
        - FAISS 인덱스는 soft-delete (검색 결과에서 expired_ids 필터링)

        Returns:
            제거된 씨앗 수
        """
        now = time.time()
        expired_ids = [
            sid for sid, (_, seed) in self.seed_registry.items()
            if (now - seed.timestamp) > seed.ttl_seconds
        ]
        for sid in expired_ids:
            del self.seed_registry[sid]
            self._claimed_seeds.pop(sid, None)

        if expired_ids:
            # FAISS hard-delete
            self.faiss_registry.evict_seeds(set(expired_ids))
            # Redis(또는 로컬 폴백) 에서도 제거 — 분산 환경 메모리 누수 차단
            for sid in expired_ids:
                self.store.remove_seed(sid)
            print(f"[DataUniverse] ♻  {len(expired_ids)}개 씨앗 TTL 만료 → 레지스트리 + FAISS + Store 정리 완료.")
        return len(expired_ids)


    # ─── 필드 진화 (확산 방정식) ─────────────────────────────────

    def propagate(self, dt: float = 1.0) -> None:
        """
        스티그머지 확산 방정식으로 필드 진화:
        ∂φ/∂t = D·∇²φ - ρ·φ
        
        - D·∇²φ : 확산 항 (정보가 공간으로 퍼짐)
        - -ρ·φ  : 감쇠 항 (오래된 신호 자동 소멸)
        """
        # TTL 초과 씨앗 정리 (매 tick마다 증발 — 메모리 누수 방지)
        self.evict_expired_seeds()

        # 멀티프로세스 환경 동기화:
        # 1. 타 프로세스가 투하한 씨앗을 로컬 레지스트리에 반영
        # 2. 타 프로세스가 변경한 최신 필드 벡터 로드
        if self.store.is_active:
            self.sync_seed_registry_from_store()
            self.field = self.store.load_field(self.grid_size, self.dim)

        # 1D 라플라시안 ∇²φ (순환 경계 조건)
        laplacian = (
            np.roll(self.field, 1, axis=0)
            + np.roll(self.field, -1, axis=0)
            - 2 * self.field
        )

        # 확산-감쇠 방정식 적용
        self.field = (
            self.field
            + dt * self.diffusion_rate * laplacian
            - dt * self.decay_rate * self.field
        )

        # 필드 클리핑 (수치 안정성)
        self.field = np.clip(self.field, -10.0, 10.0)

        # 진화된 필드 상태 Redis에 전송 및 싱크
        self.store.save_field(self.field)

        self._tick += 1
        if self._tick % self.snapshot_interval == 0:
            self.field_snapshots.append(self.field.copy())
            # 스냅샷 상한 유지 (최근 20개만 보관 — TDA는 최신 데이터만 필요)
            if len(self.field_snapshots) > 20:
                self.field_snapshots.pop(0)

    # ─── 밀도 감지 (에이전트의 공명 탐지 지원) ──────────────────

    def get_field_at(self, position: int) -> np.ndarray:
        """특정 위치의 필드 벡터 반환"""
        # Redis 연동 상태일 경우 실시간으로 필드 셀 상태를 확인하기 위해 최신화 동기화 수행
        if self.store.is_active:
            self.field = self.store.load_field(self.grid_size, self.dim)
        return self.field[position % self.grid_size]

    def get_density_gradient(self, position: int) -> np.ndarray:
        """
        특정 위치에서의 밀도 기울기 (중력 아날로그).
        에이전트가 '끌려가는' 방향 = 정보 밀도가 높은 방향.
        """
        if self.store.is_active:
            self.field = self.store.load_field(self.grid_size, self.dim)
        pos = position % self.grid_size
        forward = self.field[(pos + 1) % self.grid_size]
        backward = self.field[(pos - 1) % self.grid_size]
        return (forward - backward) / 2.0

    def get_global_energy(self) -> float:
        """전체 필드의 총 에너지 (||φ||²의 합)"""
        if self.store.is_active:
            self.field = self.store.load_field(self.grid_size, self.dim)
        return float(np.sum(self.field ** 2))

    def get_active_seeds(self, min_energy_threshold: float = 0.1) -> List[Tuple[int, Seed]]:
        """
        현재 활성 씨앗들의 목록 반환.
        (에너지가 충분히 남아 있는 씨앗들)
        """
        if self.store.is_active:
            self.field = self.store.load_field(self.grid_size, self.dim)
            seeds = self.store.get_active_seeds(self.dim)
            active = []
            for pos, seed in seeds:
                local_energy = float(np.linalg.norm(self.field[pos]))
                if local_energy > min_energy_threshold:
                    active.append((pos, seed))
            return active

        active = []
        for seed_id, (pos, seed) in self.seed_registry.items():
            # 해당 위치의 필드 에너지로 활성 여부 판단
            local_energy = float(np.linalg.norm(self.field[pos]))
            if local_energy > min_energy_threshold:
                active.append((pos, seed))
        return active

    def get_snapshot_history(self) -> List[np.ndarray]:
        """TDA 분석을 위한 필드 스냅샷 히스토리"""
        return self.field_snapshots

    def __repr__(self):
        seed_count = len(self.store.get_active_seeds(self.dim)) if self.store.is_active else len(self.seed_registry)
        return (f"DataUniverseField(dim={self.dim}, grid={self.grid_size}, "
                f"energy={self.get_global_energy():.4f}, "
                f"seeds={seed_count}, tick={self._tick})")
