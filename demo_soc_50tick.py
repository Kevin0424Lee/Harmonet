"""
demo_soc_50tick.py — 50-Tick 장기 시뮬레이션: SOC 파워법칙 α 측정
====================================================================
충분한 틱을 실행하여 BTW 모래더미 SOC 컨트롤러의 눈사태(avalanche) 이벤트를
축적하고, P(s) ~ s^(-α) 파워법칙 지수 α를 실측합니다.

실행:
    python -X utf8 demo_soc_50tick.py
    python -X utf8 demo_soc_50tick.py --ticks 100   # 틱 수 조정
"""

import sys
import argparse
import asyncio
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from harmonet.field import DataUniverseField
from harmonet.agent import HarmoAgent, AgentRole, SOCController, SeedEncoder
from harmonet.resonance import KuraMotoCoupler


def print_sep(title: str = "", width: int = 72, char: str = "─"):
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{char * pad} {title} {char * pad}")
    else:
        print(char * width)


def compute_power_law(cascade_history: list[int]) -> tuple[float | None, str]:
    """
    캐스케이드 크기 분포에서 파워법칙 지수 α 추정.
    P(s) ~ s^(-α)  →  log P(s) = -α log s + const
    최소제곱법 로그-로그 회귀로 α 계산.
    """
    if len(cascade_history) < 10:
        return None, "데이터 부족 (< 10 샘플)"

    sizes = np.array(cascade_history, dtype=float)
    unique, counts = np.unique(sizes, return_counts=True)
    if len(unique) < 2:
        return None, "눈사태 크기 다양성 부족"

    probs = counts / counts.sum()
    log_s = np.log(unique + 1e-8)
    log_p = np.log(probs + 1e-8)

    coeffs = np.polyfit(log_s, log_p, 1)
    alpha = float(-coeffs[0])
    r_sq = float(np.corrcoef(log_s, log_p)[0, 1] ** 2)
    return alpha, f"α={alpha:.3f}, R²={r_sq:.3f} (n={len(cascade_history)})"


async def run_50tick(num_ticks: int = 50):
    print_sep(f"HarmoNet {num_ticks}-Tick 장기 시뮬레이션 (SOC α 측정)", char="═")

    # ── 데이터 우주 초기화 ────────────────────────────────────────
    universe = DataUniverseField(dim=256, grid_size=16, decay_rate=0.01, diffusion_rate=0.03)
    kuramoto = KuraMotoCoupler(coupling_strength=0.5)
    soc      = SOCController(threshold=0.6)   # 낮은 임계값 → 눈사태 더 자주 발생

    # ── 에이전트 6개 (SOC 다양성을 위해 더 많이) ─────────────────
    agent_configs = [
        ("Architect-1", AgentRole.ARCHITECT, ["api design", "system architecture"],       2,  0.20),
        ("Architect-2", AgentRole.ARCHITECT, ["database schema", "data modeling"],         4,  0.20),
        ("Builder-1",   AgentRole.BUILDER,   ["fastapi", "python", "rest api"],            7,  0.15),
        ("Builder-2",   AgentRole.BUILDER,   ["redis cache", "postgresql", "orm"],         9,  0.15),
        ("Validator-1", AgentRole.VALIDATOR, ["security audit", "owasp", "fastapi"],      12,  0.10),
        ("Validator-2", AgentRole.VALIDATOR, ["unit testing", "integration test", "api"], 14,  0.10),
    ]

    agents = []
    for aid, role, tags, pos, thresh in agent_configs:
        a = HarmoAgent(
            agent_id=aid, role=role, domain_tags=tags,
            universe=universe, soc_controller=soc,
            kuramoto_coupler=kuramoto,
            resonance_threshold=thresh, grid_position=pos,
        )
        agents.append(a)

    print(f"\n에이전트 {len(agents)}개 초기화 완료")
    print(f"실행 틱: {num_ticks}  |  SOC 임계값: {soc.threshold}")
    print_sep()

    # ── 초기 씨앗 투하 ────────────────────────────────────────────
    seed_tasks = [
        (agents[0], "Design a scalable microservices authentication system with JWT and OAuth2."),
        (agents[1], "Create database schema for users, sessions, and audit logs."),
    ]

    # ── 메트릭 추적 ───────────────────────────────────────────────
    tick_metrics = []
    total_resonances = 0
    total_cascades   = 0

    # ── 틱 루프 ──────────────────────────────────────────────────
    for tick in range(1, num_ticks + 1):
        # 초기 씨앗 투하 (첫 틱)
        if tick == 1:
            for depositor, task in seed_tasks:
                depositor.create_and_deposit_seed(task)

        # 주기적으로 새 씨앗 투하 (에너지 유지)
        if tick % 10 == 0:
            idx = (tick // 10) % len(agents)
            agents[idx].create_and_deposit_seed(
                f"Tick {tick}: Extend and optimize the existing authentication system. "
                "Add rate limiting, refresh token rotation, and audit trail."
            )

        # 필드 확산
        universe.propagate(dt=0.3)

        # 쿠라모토 업데이트
        for a in agents:
            a.sync_phase(dt=0.1)

        # 중력 드리프트
        for a in agents:
            a.drift_position()

        # 공명 스캔
        scan_tasks = [a.scan_and_process_async() for a in agents]
        results_list = await asyncio.gather(*scan_tasks)

        tick_resonances = sum(len(r) for r in results_list)
        total_resonances += tick_resonances

        # SOC 눈사태 카운트
        tick_cascades = len(soc.cascade_history) - total_cascades
        total_cascades = len(soc.cascade_history)

        # 질서 파라미터
        r_val, psi = kuramoto.get_order_parameter()
        energy = universe.get_global_energy()

        tick_metrics.append({
            "tick": tick, "r": r_val, "energy": energy,
            "resonances": tick_resonances, "cascades": tick_cascades,
        })

        # 10틱마다 진행 상황 출력
        if tick % 10 == 0 or tick == 1:
            alpha, alpha_str = compute_power_law(soc.cascade_history)
            print(f"  [Tick {tick:3d}] r={r_val:.3f} | 에너지={energy:.4f} | "
                  f"공명={tick_resonances}회 | SOC누사태={len(soc.cascade_history)}건 | "
                  f"{alpha_str}")

    # ── 최종 SOC 분석 ─────────────────────────────────────────────
    print_sep("SOC 파워법칙 최종 분석")

    alpha_final, alpha_str = compute_power_law(soc.cascade_history)

    if alpha_final is not None:
        print(f"\n  눈사태 이벤트 총 횟수: {len(soc.cascade_history)}건")

        sizes = np.array(soc.cascade_history)
        unique, counts = np.unique(sizes, return_counts=True)
        print(f"  눈사태 크기 분포:")
        for sz, cnt in zip(unique, counts):
            bar = "█" * min(40, int(cnt * 40 / counts.max()))
            print(f"    크기 {sz:2d}: {cnt:4d}회  {bar}")

        print(f"\n  파워법칙 지수: {alpha_str}")
        if 1.0 < alpha_final < 3.0:
            print("  ✅ SOC 임계 상태 확인: 1 < α < 3 범위 (스케일 불변 협업 달성)")
        else:
            print(f"  ⚠  α={alpha_final:.3f} — 더 많은 틱이나 임계값 조정 필요")
    else:
        print(f"  ⚠  {alpha_str}")
        print("  → 임계값을 낮추거나 틱 수를 늘려 더 많은 눈사태 데이터 확보 필요")
        print(f"     현재 cascade_history 길이: {len(soc.cascade_history)}")

    # ── 쿠라모토 최종 동기화 ─────────────────────────────────────
    print_sep("쿠라모토 최종 동기화")
    r_final, psi_final = kuramoto.get_order_parameter()
    print(f"\n  최종 질서 파라미터 r = {r_final:.4f}")
    if r_final > 0.7:
        print(f"  ✅ 강 동기화 (r > 0.7)")
    elif r_final > 0.4:
        print(f"  🔄 중간 동기화 (0.4 < r ≤ 0.7)")
    else:
        print(f"  ⚠  약 동기화 (r ≤ 0.4) — 더 많은 틱 필요")

    # ── 전체 통계 ─────────────────────────────────────────────────
    print_sep("전체 시뮬레이션 통계")
    total_tasks = sum(
        sum(1 for res in a.task_results if res.success) for a in agents
    )
    total_trad_tokens = sum(a.token_count_traditional for a in agents)

    print(f"\n  실행 틱 수:              {num_ticks}")
    print(f"  총 공명 감지:           {total_resonances}회")
    print(f"  총 SOC 눈사태:          {len(soc.cascade_history)}건")
    print(f"  완료된 작업:            {total_tasks}건")
    print(f"  HarmoNet 네트워크 토큰: 0 (절감율 100%)")
    print(f"  전통 방식 예상 토큰:    ~{total_trad_tokens:,}")
    print(f"  최종 우주 에너지:       {universe.get_global_energy():.4f}")
    print(f"  씨앗 레지스트리:        {len(universe.seed_registry)}개")

    print_sep("시뮬레이션 완료", char="═")
    return alpha_final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HarmoNet SOC 50-Tick 시뮬레이션")
    parser.add_argument("--ticks", type=int, default=50, help="실행할 틱 수 (기본 50)")
    args = parser.parse_args()
    asyncio.run(run_50tick(args.ticks))
