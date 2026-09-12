"""
ResonanceDetector: 쿠라모토 모델 기반 공명 감지기
===================================================
에이전트가 자신과 관련 있는 신호만 선택적으로 감지.

이론적 기반:
- 쿠라모토 위상 동기화: dθᵢ/dt = ωᵢ + K/N·∑ⱼ sin(θⱼ-θᵢ)
- 감마파 CTC 이론: |ω_A - ω_B| < δ → 통신 채널 개방
- 질서 파라미터: r·e^{iψ} = (1/N)·∑ⱼ e^{iθⱼ} (동기화 강도)
- TDA: Betti 수 β₀, β₁ 변화 → 진짜 공명 vs 노이즈 구분
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import time

from .field import Seed, DataUniverseField


@dataclass
class ResonanceEvent:
    """공명 감지 이벤트"""
    detector_id: str          # 감지한 에이전트 ID
    seed: Seed                # 공명한 씨앗
    resonance_strength: float # 공명 강도 (0~1)
    phase_diff: float         # 위상 차이
    timestamp: float = field(default_factory=time.time)

    def __repr__(self):
        return (f"ResonanceEvent({self.detector_id} ← {self.seed.creator_id}, "
                f"강도={self.resonance_strength:.3f}, 위상차={self.phase_diff:.3f})")


class KuraMotoCoupler:
    """
    쿠라모토 모델 기반 위상 동기화 엔진.
    
    수학 모델:
    dθᵢ/dt = ωᵢ + (K/N) · ∑ⱼ sin(θⱼ - θᵢ)
    
    - θᵢ   : 에이전트 i의 현재 위상
    - ωᵢ   : 에이전트 i의 고유 주파수 (작업 도메인 특성)
    - K    : 결합 강도 (에이전트 간 상호작용 강도)
    - N    : 총 에이전트 수
    """

    def __init__(self, coupling_strength: float = 0.5):
        self.base_K = coupling_strength  # 기본 결합 강도
        self.K = coupling_strength       # 결합 강도 K (동적 변화)
        self.phases: dict = {}      # {agent_id: current_phase θ}
        self.frequencies: dict = {} # {agent_id: natural_frequency ω}

    def register_agent(self, agent_id: str, natural_frequency: float) -> None:
        """에이전트를 쿠라모토 커플러에 등록"""
        self.phases[agent_id] = np.random.uniform(0, 2 * np.pi)  # 초기 위상 랜덤
        self.frequencies[agent_id] = natural_frequency

    def step(self, dt: float = 0.1) -> None:
        """
        쿠라모토 ODE를 dt만큼 적분:
        dθᵢ/dt = ωᵢ + (K/N) · ∑ⱼ sin(θⱼ - θᵢ)
        """
        N = len(self.phases)
        if N < 2:
            return

        agent_ids = list(self.phases.keys())
        phases = np.array([self.phases[agent_id] for agent_id in agent_ids], dtype=np.float64)
        frequencies = np.array([self.frequencies[agent_id] for agent_id in agent_ids], dtype=np.float64)

        complex_order = np.mean(np.exp(1j * phases))
        r = abs(complex_order)
        psi = np.angle(complex_order)

        # 질서 파라미터 r을 계산하여 결합 강도 K를 동적으로 적응 (CTC 모델)
        self.K = self.base_K * (1.5 - r)

        # ∑ⱼ sin(θⱼ - θᵢ)는 order parameter로 N*r*sin(ψ-θᵢ)와 동치.
        # 기존 O(N²) 모든 쌍 합산을 O(N) 벡터 연산으로 축약한다.
        coupling_sum = N * r * np.sin(psi - phases)
        dtheta = frequencies + (self.K / N) * coupling_sum
        new_phases = phases + dt * dtheta
        self.phases = {
            agent_id: float(phase)
            for agent_id, phase in zip(agent_ids, new_phases)
        }

    def get_order_parameter(self) -> Tuple[float, float]:
        """
        쿠라모토 질서 파라미터 계산:
        r·e^{iψ} = (1/N)·∑ⱼ e^{iθⱼ}
        
        Returns:
            (r, ψ): 동기화 강도(0~1), 집단 평균 위상
        """
        if not self.phases:
            return 0.0, 0.0
        phases = np.array(list(self.phases.values()))
        complex_order = np.mean(np.exp(1j * phases))
        r = abs(complex_order)
        psi = np.angle(complex_order)
        return float(r), float(psi)

    def get_phase(self, agent_id: str) -> float:
        """특정 에이전트의 현재 위상"""
        return self.phases.get(agent_id, 0.0)


class ResonanceDetector:
    """
    공명 감지기.
    
    감마파 CTC(Communication Through Coherence) 이론 구현:
    |ω_A - ω_B| < δ → 통신 채널 개방 (공명 감지)
    |ω_A - ω_B| > δ → 신호 차단 (노이즈로 취급)
    
    에이전트의 '주파수'는 현재 담당하는 작업의 도메인 특성 벡터.
    관련된 작업을 수행하는 에이전트끼리 주파수가 가까워 자동 공명.
    """

    def __init__(
        self,
        agent_id: str,
        domain_vector: np.ndarray,      # 에이전트의 작업 도메인 특성
        resonance_threshold: float = 0.5,   # 공명 임계값 δ (코사인 유사도)
        min_seed_energy: float = 0.05,  # 감지할 씨앗의 최소 에너지
    ):
        """
        Args:
            agent_id:            에이전트 고유 ID
            domain_vector:       에이전트의 작업 도메인 특성 벡터 (고유 주파수 ω)
            resonance_threshold: 공명 임계값 δ. 높을수록 선택적, 낮을수록 광범위
            min_seed_energy:     감지할 씨앗의 최소 에너지 (ħ 아날로그)
        """
        self.agent_id = agent_id
        self.omega = domain_vector / (np.linalg.norm(domain_vector) + 1e-8)  # 정규화
        self.delta = resonance_threshold
        self.min_energy = min_seed_energy

        # 감지된 공명 이벤트 히스토리
        self.resonance_history: List[ResonanceEvent] = []

        # 자체 위상 (쿠라모토 모델용)
        self.phase: float = np.random.uniform(0, 2 * np.pi)

        # ─── 적응형 δ 조정 상태 ──────────────────────────────────
        # 최근 스캔에서 관찰된 코사인 유사도 샘플 (롤링 200개)
        self._recent_similarities: List[float] = []
        self._scan_count: int = 0      # 스캔 횟수 (5회마다 δ 재평가)
        self.delta_min: float = 0.05   # δ 허용 하한
        self.delta_max: float = 0.95   # δ 허용 상한

    # ─── 핵심 공명 감지 로직 ─────────────────────────────────────

    def scan_field(
        self,
        universe: DataUniverseField,
        scan_position: int,
        scan_radius: int = 3,
    ) -> List[ResonanceEvent]:
        """
        데이터 우주 필드를 스캔하여 공명하는 씨앗들을 감지.
        
        CTC 이론: 주파수 유사도가 임계값 δ 이상일 때만 수신.
        
        Args:
            universe:      데이터 우주 필드
            scan_position: 스캔 중심 위치
            scan_radius:   스캔 반경
            
        Returns:
            감지된 공명 이벤트 목록
        """
        detected = []

        # 1. FAISS 인덱스가 활성화되어 있다면 고속 벡터 인덱스 쿼리 수행
        if hasattr(universe, "faiss_registry") and universe.faiss_registry.is_active:
            # TTL 만료 씨앗 ID 집합 — FAISS soft-delete 필터링에 사용
            now = time.time()
            expired_ids = {
                sid for sid, (_, seed) in universe.seed_registry.items()
                if (now - seed.timestamp) > seed.ttl_seconds
            }
            # 주파수(도메인) 유사도 >= delta 인 상위 10개 후보군을 먼저 FAISS로 고속 스캔
            candidates = universe.faiss_registry.search_seeds(
                self.omega, top_k=10, min_similarity=self.delta, expired_ids=expired_ids
            )
            
            for seed, cosine_sim in candidates:
                if seed.creator_id == self.agent_id:
                    continue

                # 위치 값 확인
                grid_pos = 0
                if seed.id in universe.seed_registry:
                    grid_pos = universe.seed_registry[seed.id][0]
                elif universe.store.is_active:
                    try:
                        pos_val = universe.store.client.hget(f"{universe.store.prefix}:seeds:positions", seed.id)
                        if pos_val:
                            grid_pos = int(pos_val.decode("utf-8"))
                    except Exception as e:
                        # 위치를 모르면 거리 필터가 무의미해진다. Redis 오류는 store 의 폴백 규칙을 따른다 (명시 허용 없으면 예외)
                        from .store import _fallback_or_raise
                        _fallback_or_raise(f"씨앗 위치 조회 실패 ({str(e)})")
                        continue

                # 거리 필터
                distance = abs(grid_pos - scan_position)
                if distance > scan_radius:
                    continue

                # 위상 차이 계산 (쿠라모토 모델 기반 CTC)
                d_theta = abs(self.phase - seed.phase) % (2 * np.pi)
                phase_diff = min(d_theta, 2 * np.pi - d_theta)
                coherence = float(max(0.0, np.cos(phase_diff)))

                # FAISS가 이미 cosine_sim >= delta를 보장. strength는 로깅용.
                effective_coherence = max(0.2, coherence)
                resonance_strength = cosine_sim * effective_coherence * np.exp(-0.1 * distance)

                event = ResonanceEvent(
                    detector_id=self.agent_id,
                    seed=seed,
                    resonance_strength=resonance_strength,
                    phase_diff=phase_diff,
                )
                detected.append(event)
                self.resonance_history.append(event)
                # 히스토리 상한 — 최근 500개만 보관
                if len(self.resonance_history) > 500:
                    self.resonance_history = self.resonance_history[-250:]

                print(f"[Resonance - FAISS] ⚡ 공명 감지! {self.agent_id} ← {seed.creator_id} | "
                      f"유사도={cosine_sim:.3f} > δ={self.delta:.2f} | "
                      f"위상차={phase_diff:.3f} rad, 동기성={coherence:.3f} | "
                      f"강도={resonance_strength:.3f}")

            # 적응형 δ 업데이트 (FAISS 후보군 유사도 기반)
            candidate_sims = [float(score) for _, score in candidates]
            self.update_adaptive_delta(candidate_sims, len(detected), len(candidates))
            return detected

        # 2. 로컬 브루트포스 폴백
        active_seeds = universe.get_active_seeds(self.min_energy)

        for grid_pos, seed in active_seeds:
            # 자신이 만든 씨앗은 감지 안 함
            if seed.creator_id == self.agent_id:
                continue

            # 거리 필터: 스캔 반경 내에 있는 씨앗만
            distance = abs(grid_pos - scan_position)
            if distance > scan_radius:
                continue

            # ─── 핵심: CTC 공명 조건 ───────────────────────────
            # 에이전트의 주파수 벡터(ω)와 씨앗의 주파수 벡터 간 코사인 유사도
            seed_freq = seed.frequency / (np.linalg.norm(seed.frequency) + 1e-8)
            cosine_sim = float(np.dot(self.omega, seed_freq))

            # 위상 차이 계산 (쿠라모토 모델 기반 CTC)
            d_theta = abs(self.phase - seed.phase) % (2 * np.pi)
            phase_diff = min(d_theta, 2 * np.pi - d_theta)
            coherence = float(max(0.0, np.cos(phase_diff)))

            # 공명 조건: cosine_sim >= δ 이면 공명 허용
            if cosine_sim >= self.delta:
                effective_coherence = max(0.2, coherence)
                resonance_strength = cosine_sim * effective_coherence * np.exp(-0.1 * distance)

                event = ResonanceEvent(
                    detector_id=self.agent_id,
                    seed=seed,
                    resonance_strength=resonance_strength,
                    phase_diff=phase_diff,
                )
                detected.append(event)
                self.resonance_history.append(event)
                if len(self.resonance_history) > 500:
                    self.resonance_history = self.resonance_history[-250:]

                print(f"[Resonance] ⚡ 공명 감지! {self.agent_id} ← {seed.creator_id} | "
                      f"유사도={cosine_sim:.3f} > δ={self.delta:.2f} | "
                      f"위상차={phase_diff:.3f} rad, 동기성={coherence:.3f} | "
                      f"강도={resonance_strength:.3f}")

        # 적응형 δ 업데이트 (브루트포스 경로: 전체 후보 유사도 수집)
        all_sims: List[float] = []
        for _, s in active_seeds:
            if s.creator_id == self.agent_id:
                continue
            freq = s.frequency / (np.linalg.norm(s.frequency) + 1e-8)
            all_sims.append(float(np.dot(self.omega, freq)))
        self.update_adaptive_delta(all_sims, len(detected), len(all_sims))

        return detected

    def update_adaptive_delta(
        self,
        candidate_similarities: List[float],
        resonance_count: int,
        candidate_count: int,
    ) -> None:
        """
        최근 스캔 결과를 바탕으로 공명 임계값 δ를 동적으로 조정.

        과다 공명 (resonance_rate > 50%): δ 상향 → 더 선택적으로
        과소 공명 (resonance_rate < 5%):  δ 하향 → 더 수용적으로

        보폭 ±0.02: 급격한 진동 방지.  5회 스캔마다 1회 평가.
        """
        self._recent_similarities.extend(candidate_similarities)
        # 롤링 윈도우 상한 유지
        if len(self._recent_similarities) > 200:
            self._recent_similarities = self._recent_similarities[-100:]

        self._scan_count += 1
        if self._scan_count % 5 != 0 or candidate_count == 0:
            return

        resonance_rate = resonance_count / max(1, candidate_count)

        if resonance_rate > 0.5:
            # 너무 많은 공명 → δ 상향
            new_delta = min(self.delta_max, self.delta + 0.02)
            if new_delta != self.delta:
                print(f"[Resonance] 📈 적응형 δ 상향: {self.delta:.3f} → {new_delta:.3f} "
                      f"(공명율={resonance_rate:.1%}, 에이전트={self.agent_id})")
                self.delta = new_delta

        elif resonance_rate < 0.05 and len(self._recent_similarities) >= 10:
            # 너무 적은 공명 — 단, 유사도 분포 자체가 낮을 때만 하향
            p70 = float(np.percentile(self._recent_similarities, 70))
            if p70 < self.delta - 0.1:
                new_delta = max(self.delta_min, self.delta - 0.02)
                if new_delta != self.delta:
                    print(f"[Resonance] 📉 적응형 δ 하향: {self.delta:.3f} → {new_delta:.3f} "
                          f"(공명율={resonance_rate:.1%}, p70_sim={p70:.3f}, "
                          f"에이전트={self.agent_id})")
                    self.delta = new_delta

    def detect_from_seed(self, seed: Seed) -> Optional[ResonanceEvent]:
        """
        단일 씨앗에 대한 직접 공명 검사.
        에너지가 최소치 이상이고 주파수가 매칭될 때만 공명.
        """
        if seed.creator_id == self.agent_id:
            return None

        seed_freq = seed.frequency / (np.linalg.norm(seed.frequency) + 1e-8)
        cosine_sim = float(np.dot(self.omega, seed_freq))

        if cosine_sim >= self.delta and seed.energy >= self.min_energy:
            d_theta = abs(self.phase - seed.phase) % (2 * np.pi)
            phase_diff = min(d_theta, 2 * np.pi - d_theta)
            coherence = float(max(0.0, np.cos(phase_diff)))

            effective_coherence = max(0.2, coherence)
            event = ResonanceEvent(
                detector_id=self.agent_id,
                seed=seed,
                resonance_strength=cosine_sim * effective_coherence,
                phase_diff=phase_diff,
            )
            self.resonance_history.append(event)
            if len(self.resonance_history) > 500:
                self.resonance_history = self.resonance_history[-250:]
            return event
        return None


    # ─── TDA 기반 공명 검증 ──────────────────────────────────────

    def validate_resonance_with_betti(
        self,
        before_snapshot: np.ndarray,
        after_snapshot: np.ndarray,
    ) -> Tuple[bool, str]:
        """
        TDA Persistent Homology로 공명 신호 검증.
        1차원 Persistent Homology는 단일 연결 계층적 클러스터링(scipy.cluster.hierarchy.linkage)과
        동형(Isomorphic) 관계에 있습니다. 이를 통해 고차원 데이터 공간에서 Betti 0 지속성을 계산하고,
        Wasserstein 거리를 통해 유효한 장의 위상 변화가 있었는지 판별합니다.
        """
        # ── 조기 종료: 필드 에너지 변화가 없으면 TDA 전체 스킵 ────
        energy_change = float(np.linalg.norm(after_snapshot - before_snapshot))
        if energy_change < 1e-6:
            return True, f"필드 변화 없음 (Δ={energy_change:.2e}) — TDA 스킵"

        try:
            return self._tda_with_scipy(before_snapshot, after_snapshot)
        except Exception as e:
            # SciPy 에러 또는 모듈 누락 시 단순 통계 근사로 fallback
            try:
                return self._tda_approximation(before_snapshot, after_snapshot)
            except Exception as e_inner:
                # 예외를 '유효' 판정으로 바꾸던 조용한 폴백 제거 (WEEK1 A2). 실패는 실패로 돌려준다.
                return False, f"TDA 계산 실패 (근사 경로도 실패): {str(e_inner)}"

    def _tda_with_scipy(
        self,
        before: np.ndarray,
        after: np.ndarray,
    ) -> Tuple[bool, str]:
        """
        SciPy 계층적 클러스터링을 사용한 Betti 0 Persistent Homology 계산.
        Wasserstein 거리를 이용해 위상학적 변화가 유효한지 검증합니다.
        """
        from scipy.cluster.hierarchy import linkage

        # ── 대형 그리드 서브샘플링 (linkage O(N²) 병목 완화) ────────
        # grid_size가 큰 경우 최대 64점만 무작위 선택.
        # 384-dim × 64점 기준 linkage는 ~1ms 이내 → 실질 병목 해소.
        MAX_SAMPLES = 64
        if len(before) > MAX_SAMPLES:
            idx = np.random.choice(len(before), MAX_SAMPLES, replace=False)
            before_sub = before[idx]
            after_sub = after[idx]
        else:
            before_sub = before
            after_sub = after

        # 수치적 안정성을 위해 미세한 노이즈 주입 (완벽 중복 위치점 에러 방지)
        noise = 1e-6
        before_noisy = before_sub + np.random.randn(*before_sub.shape) * noise
        after_noisy = after_sub + np.random.randn(*after_sub.shape) * noise

        # Single Linkage 클러스터링 수행 (Betti 0 지속성 여과와 수학적 동형)
        z_before = linkage(before_noisy, method='single', metric='euclidean')
        z_after = linkage(after_noisy, method='single', metric='euclidean')
        
        # 병합 거리 Z[:, 2]가 곧 Betti 0 component들의 소멸 시간(death times)
        deaths_before = np.sort(z_before[:, 2])
        deaths_after = np.sort(z_after[:, 2])
        
        # 두 지속성 다이어그램 간 1-Wasserstein 거리를 소멸 시간 차이의 합으로 계산
        wasserstein_dist = float(np.sum(np.abs(deaths_before - deaths_after)))
        
        # 위상 변형 임계값
        threshold = 0.05
        is_valid = wasserstein_dist > threshold
        
        reason = f"Betti 0 Wasserstein 거리: {wasserstein_dist:.4f} (임계값={threshold})"
        return is_valid, reason

    def _tda_approximation(
        self,
        before: np.ndarray,
        after: np.ndarray,
    ) -> Tuple[bool, str]:
        """
        gudhi 없이 수행하는 TDA 근사:
        필드 에너지 분포의 통계적 변화로 Betti 수 변화 추정.
        """
        # 각 그리드 위치의 에너지 (L2 노름)
        energy_before = np.linalg.norm(before, axis=1)
        energy_after = np.linalg.norm(after, axis=1)

        # β₀ 근사: 에너지 임계값 이상인 클러스터 수 변화
        threshold = np.mean(energy_after) + 0.5 * np.std(energy_after)
        clusters_before = self._count_clusters(energy_before > np.mean(energy_before))
        clusters_after = self._count_clusters(energy_after > threshold)

        # β₁ 근사: 에너지 분포의 표준편차 변화 (이질성 = 루프 형성)
        std_change = abs(np.std(energy_after) - np.std(energy_before))

        beta0_changed = clusters_before != clusters_after
        beta1_changed = std_change > 0.1

        is_valid = beta0_changed or beta1_changed
        reason = f"β₀ 변화: {clusters_before}→{clusters_after}, β₁ 변화: {std_change:.3f}"

        return is_valid, reason

    def _count_clusters(self, binary_array: np.ndarray) -> int:
        """연속된 True 구간의 수 (β₀ 근사)"""
        if not np.any(binary_array):
            return 0
        count = 0
        in_cluster = False
        for val in binary_array:
            if val and not in_cluster:
                count += 1
                in_cluster = True
            elif not val:
                in_cluster = False
        return count

    def _tda_with_gudhi(
        self,
        before: np.ndarray,
        after: np.ndarray,
    ) -> Tuple[bool, str]:
        """gudhi를 사용한 실제 Persistent Homology 계산"""
        import gudhi

        def compute_betti(snapshot):
            rips = gudhi.RipsComplex(points=snapshot, max_edge_length=2.0)
            simplex_tree = rips.create_simplex_tree(max_dimension=2)
            simplex_tree.compute_persistence()
            return simplex_tree.betti_numbers()

        betti_before = compute_betti(before)
        betti_after = compute_betti(after)

        beta0_changed = betti_before[0] != betti_after[0] if len(betti_before) > 0 else False
        beta1_changed = (betti_before[1] != betti_after[1]
                         if len(betti_before) > 1 and len(betti_after) > 1 else False)

        is_valid = beta0_changed or beta1_changed
        reason = f"β₀: {betti_before[0] if betti_before else '?'}→{betti_after[0] if betti_after else '?'}"
        return is_valid, reason

    def get_resonance_history(self) -> List[ResonanceEvent]:
        """감지된 공명 이벤트 히스토리"""
        return self.resonance_history

    def __repr__(self):
        return (f"ResonanceDetector(agent={self.agent_id}, "
                f"δ={self.delta:.2f}, "
                f"events={len(self.resonance_history)})")
