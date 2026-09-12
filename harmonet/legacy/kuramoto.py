"""
harmonet/legacy/kuramoto.py — Kuramoto 위상 동기화 (legacy)

주 경로에서 제외됨 (WEEK1 A3). HARMONET_LEGACY_MECHANISMS=1 일 때만 HarmoAgent 가 사용한다.
삭제하지 않는 이유: 논문에서 "시도했고 기여가 없었다"고 서술할 근거로 보존.
"""
import numpy as np
from typing import Dict, Tuple


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
