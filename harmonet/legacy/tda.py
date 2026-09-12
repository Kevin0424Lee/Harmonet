"""
harmonet/legacy/tda.py — TDA(Betti-0 persistent homology) 공명 검증 (legacy)

주 경로에서 제외됨 (WEEK1 A3). HARMONET_LEGACY_MECHANISMS=1 일 때만 HarmoAgent 가 호출한다.
원래 ResonanceDetector 의 메서드였으며, 첫 인자 `detector` 로 같은 상태(delta, resonance_history, agent_id)를 받는다.
"""
import numpy as np
from typing import Tuple


def validate_resonance_with_betti(detector,
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
        return _tda_with_scipy(detector, before_snapshot, after_snapshot)
    except Exception as e:
        # SciPy 에러 또는 모듈 누락 시 단순 통계 근사로 fallback
        try:
            return _tda_approximation(detector, before_snapshot, after_snapshot)
        except Exception as e_inner:
            # 예외를 '유효' 판정으로 바꾸던 조용한 폴백 제거 (WEEK1 A2). 실패는 실패로 돌려준다.
            return False, f"TDA 계산 실패 (근사 경로도 실패): {str(e_inner)}"

def _tda_with_scipy(detector,
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

def _tda_approximation(detector,
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
    clusters_before = _count_clusters(detector, energy_before > np.mean(energy_before))
    clusters_after = _count_clusters(detector, energy_after > threshold)

    # β₁ 근사: 에너지 분포의 표준편차 변화 (이질성 = 루프 형성)
    std_change = abs(np.std(energy_after) - np.std(energy_before))

    beta0_changed = clusters_before != clusters_after
    beta1_changed = std_change > 0.1

    is_valid = beta0_changed or beta1_changed
    reason = f"β₀ 변화: {clusters_before}→{clusters_after}, β₁ 변화: {std_change:.3f}"

    return is_valid, reason

def _count_clusters(detector, binary_array: np.ndarray) -> int:
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

def _tda_with_gudhi(detector,
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
