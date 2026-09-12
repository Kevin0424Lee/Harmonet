"""
harmonet/legacy/soc.py — SOC(Bak-Tang-Wiesenfeld 모래더미) 부하 분산 (legacy)

주 경로에서 제외됨 (WEEK1 A3). HARMONET_LEGACY_MECHANISMS=1 일 때만 HarmoAgent 가 사용한다.
"""
import numpy as np
from typing import Dict, List, Optional


class SOCController:
    """
    SOC (자기조직화 임계성) 컨트롤러.
    
    Per Bak의 BTW 모래 더미 모델 구현:
    - 에이전트 부하가 임계값 초과 시 이웃 에이전트로 작업 위임 (토플링)
    - 협업 캐스케이드 = 눈사태 (avalanche)
    - P(s) ~ s^(-α) 파워 법칙으로 스케일 불변성 달성
    """

    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold
        self.activation_levels: Dict[str, float] = {}
        self.cascade_history: List[int] = []  # 눈사태 크기 기록

    def register(self, agent_id: str, initial_load: float = 0.0):
        self.activation_levels[agent_id] = initial_load

    def add_load(self, agent_id: str, load: float) -> List[str]:
        """
        부하를 추가하고 필요시 BTW 토플링 수행.
        
        Returns:
            위임받은 에이전트 ID 목록 (눈사태 참여자)
        """
        if agent_id not in self.activation_levels:
            self.activation_levels[agent_id] = 0.0

        self.activation_levels[agent_id] += load
        cascade = []

        if self.activation_levels[agent_id] > self.threshold:
            cascade = self._topple(agent_id)

        return cascade

    def _topple(self, overloaded_id: str) -> List[str]:
        """BTW 토플링: 과부하 에이전트의 작업을 이웃에게 분산"""
        neighbors = [
            aid for aid in self.activation_levels.keys()
            if aid != overloaded_id
        ]
        if not neighbors:
            return []

        # 균등 분산 (실제 구현에서는 주파수 유사도 기반 선택적 분산)
        spill = self.activation_levels[overloaded_id] * 0.5
        per_neighbor = spill / len(neighbors)

        for neighbor_id in neighbors:
            self.activation_levels[neighbor_id] += per_neighbor

        self.activation_levels[overloaded_id] -= spill
        self.cascade_history.append(len(neighbors))
        # 캐스케이드 히스토리 상한 — 파워 법칙 추정에는 최근 200개면 충분
        if len(self.cascade_history) > 200:
            self.cascade_history = self.cascade_history[-100:]

        return neighbors

    def get_power_law_exponent(self) -> Optional[float]:
        """
        캐스케이드 크기 분포의 파워 법칙 지수 α 추정.
        P(s) ~ s^(-α) → log P(s) = -α·log s + const
        """
        if len(self.cascade_history) < 10:
            return None

        sizes = np.array(self.cascade_history)
        unique, counts = np.unique(sizes, return_counts=True)
        probs = counts / counts.sum()

        # 로그-로그 선형 회귀
        log_s = np.log(unique + 1e-8)
        log_p = np.log(probs + 1e-8)

        if len(log_s) > 1:
            alpha = -np.polyfit(log_s, log_p, 1)[0]
            return float(alpha)
        return None
