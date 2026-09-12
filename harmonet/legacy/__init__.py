"""
harmonet/legacy — 주 경로에서 분리된 메커니즘 (Kuramoto · TDA · SOC)

WEEK1 A3: 삭제하지 않고 보존한다. 기본 실행 경로(HarmoAgent.scan_and_process)는 코사인 유사도 + 적응형 δ 게이트만 쓴다.
HARMONET_LEGACY_MECHANISMS=1 을 주면 에이전트가 세 메커니즘을 다시 호출한다 (어블레이션용).
"""
import os

from .kuramoto import KuraMotoCoupler
from .soc import SOCController
from .tda import validate_resonance_with_betti


def legacy_enabled() -> bool:
    return os.getenv("HARMONET_LEGACY_MECHANISMS") == "1"


__all__ = ["KuraMotoCoupler", "SOCController", "validate_resonance_with_betti", "legacy_enabled"]
