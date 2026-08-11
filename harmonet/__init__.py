"""
HarmoNet: Resonance-Triggered Seed Coding AI Collaboration Protocol
=====================================================================
공명 유도형 시드 코딩 AI 협업 프로토콜

철학적 기반: "데이터 우주(Data Universe)"
- 에이전트들은 메시지를 직접 주고받지 않는다.
- 공유 고차원 벡터 공간(데이터 우주)의 상태 변화(공명)를 통해 협업한다.
- 극도로 압축된 씨앗 수식(Seed Formula)으로만 정보를 교환한다.

이론적 기반:
- Kolmogorov 복잡도 (씨앗 수식 압축)
- 홀로그래픽 원리 / AdS-CFT (고차원 → 저차원 손실 없는 인코딩)
- QFT 장 교란 모델 (φ(x) → φ(x) + δφ_agent(x))
- 스티그머지 확산 방정식 (∂φ/∂t = D∇²φ - ρφ + S)
- 쿠라모토 동기화 모델 (dθ/dt = ω + K/N·Σsin(θⱼ-θᵢ))
- TDA Persistent Homology (공명 신호 검증)
- SOC 자기조직화 임계성 (스케일 불변 협업)
"""

__version__ = "0.1.0"
__author__ = "HarmoNet Research"

# Windows 콘솔(cp949 등)에서 한글/이모지 출력 시 UnicodeEncodeError 방지.
# Python 3.7+ sys.stdout.reconfigure()로 UTF-8 + errors='replace' 적용.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
del _sys
