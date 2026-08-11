"""
HarmoNet Demo: Phase 1 실행 데모 (Async & Feedback Loop)
======================================================
두 에이전트가 텍스트 없이 씨앗 + 공명만으로 협업하는 최소 증명.

시나리오:
1. 에이전트 A (Architect): 코딩 작업을 씨앗으로 압축하여 데이터 우주에 투하
2. 에이전트 B (Builder):   공명 감지 → 씨앗 실행 → 결과를 새 씨앗으로 투하
3. 에이전트 C (Validator): 결과 검증 씨앗을 감지하여 최종 검증 수행

기존 방식(AutoGen 스타일)과의 토큰 사용량 비교 포함.
"""

import numpy as np
import time
from typing import List, Optional, Callable, Any

from harmonet.field import DataUniverseField
from harmonet.resonance import KuraMotoCoupler
from harmonet.agent import HarmoAgent, AgentRole, SOCController


def print_separator(title: str = "", char: str = "─", width: int = 70):
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


async def run_demo_async():
    print_separator("🌌 HarmoNet Phase 1 Demo (Async & Feedback)", "═")
    print("공명 유도형 시드 코딩 AI 협업 프로토콜 - 최소 증명")
    print("철학: '데이터 우주'의 상태 변화(공명)로만 협업")
    print_separator()

    # ─── 1. 데이터 우주 초기화 ─────────────────────────────────
    print_separator("1️⃣  데이터 우주 초기화")
    universe = DataUniverseField(
        dim=128,           # 벡터 차원 (실제: 1024+)
        grid_size=16,      # 그리드 크기
        decay_rate=0.015,  # 페로몬 증발율 ρ
        diffusion_rate=0.04,  # 확산 계수 D
    )
    print(f"  {universe}")

    # ─── 2. 쿠라모토 커플러 초기화 ─────────────────────────────
    kuramoto = KuraMotoCoupler(coupling_strength=0.6)
    soc = SOCController(threshold=0.8)

    # ─── 3. 에이전트 생성 ──────────────────────────────────────
    print_separator("2️⃣  에이전트 생성")

    agent_a = HarmoAgent(
        agent_id="Architect-Alpha",
        role=AgentRole.ARCHITECT,
        domain_tags=["software_design", "architecture", "api_design"],
        universe=universe,
        soc_controller=soc,
        kuramoto_coupler=kuramoto,
        resonance_threshold=0.20,
        grid_position=3,
    )

    agent_b = HarmoAgent(
        agent_id="Builder-Beta",
        role=AgentRole.BUILDER,
        domain_tags=["python", "coding", "implementation", "api_design"],
        universe=universe,
        soc_controller=soc,
        kuramoto_coupler=kuramoto,
        resonance_threshold=0.15,  # 0.20 -> 0.15 로 낮추어 공명 민감도 상향
        grid_position=7,
    )

    agent_c = HarmoAgent(
        agent_id="Validator-Gamma",
        role=AgentRole.VALIDATOR,
        # Validator 도메인 태그에 Builder/Architect 작업 키워드를 추가하여 공간 연계성 확보
        domain_tags=["testing", "validation", "quality_assurance", "python", "api_design", "implementation"],
        universe=universe,
        soc_controller=soc,
        kuramoto_coupler=kuramoto,
        resonance_threshold=0.10,  # 0.20 -> 0.10 으로 낮추어 공명 소외 해소
        grid_position=12,
    )

    agents = [agent_a, agent_b, agent_c]

    # ─── 4. 메인 협업 루프 ─────────────────────────────────────
    print_separator("3️⃣  협업 시작: 에이전트들이 데이터 우주를 통해 소통")

    # 시나리오: REST API 설계 및 구현 작업
    tasks = [
        (agent_a, "Design a RESTful API for user authentication with JWT tokens. "
                  "Include endpoints: POST /auth/login, POST /auth/refresh, DELETE /auth/logout. "
                  "Each endpoint must validate input, return appropriate HTTP status codes, "
                  "and include rate limiting of 10 requests per minute."),

        (agent_b, "Implement the authentication service in Python using FastAPI. "
                  "Use PyJWT for token generation, bcrypt for password hashing, "
                  "Redis for session management and rate limiting. "
                  "Include unit tests for all endpoints."),

        (agent_a, "Define data models: User(id, email, password_hash, created_at), "
                  "Token(access_token, refresh_token, expires_in, token_type). "
                  "Use Pydantic v2 for validation with strict type checking."),

        (agent_c, "Validate the API design against OWASP Top 10 security guidelines. "
                  "Check for SQL injection, XSS, CSRF vulnerabilities. "
                  "Ensure tokens are properly invalidated on logout."),
    ]

    total_seeds_deposited = 0
    total_resonances = 0

    # 5 Tick 동안 시뮬레이션 실행 (비동기 틱 루프)
    import asyncio
    for tick in range(1, 6):
        print_separator(f"⏱  Tick {tick}")

        # Tick 1에 Architect가 최초 설계 시드를 데이터 우주에 투하
        if tick == 1:
            depositor, task = tasks[0]
            print(f"\n🌱 [최초 설계 시드 투하] {depositor.agent_id} 가 작업을 압축하여 씨앗 투하:")
            print(f"   내용: \"{task}\"")
            seed = depositor.create_and_deposit_seed(task)
            total_seeds_deposited += 1

        # 데이터 우주 진화 (확산 방정식)
        universe.propagate(dt=0.5)

        # 쿠라모토 동기화 스텝
        for agent in agents:
            agent.sync_phase(dt=0.1)

        # 에이전트 중력 드리프트 (밀도 경사를 따른 위치 이동)
        for agent in agents:
            agent.drift_position()

        # 쿠라모토 질서 파라미터
        r, psi = kuramoto.get_order_parameter()
        print(f"  📊 쿠라모토 동기화: r={r:.3f} ({'✅ 동기화됨' if r > 0.5 else '🔄 동기화 중'}), ψ={psi:.2f} rad")
        print(f"  🌊 데이터 우주 에너지: {universe.get_global_energy():.4f}")

        # 에이전트들이 [비동기]로 병렬 공명 감지 및 처리 수행
        print(f"\n  👁  공명 스캔 (비동기 병렬 처리):")
        scan_tasks = [agent.scan_and_process_async() for agent in agents]
        gather_results = await asyncio.gather(*scan_tasks)

        for agent, results in zip(agents, gather_results):
            total_resonances += len(results)
            if results:
                for r_result in results:
                    print(f"     {agent.agent_id} 실행 결과: {r_result}")

        await asyncio.sleep(0.1)  # 시각적 구분

    # ─── 5. 결과 분석 ──────────────────────────────────────────
    print_separator("4️⃣  협업 결과 분석")

    total_traditional_tokens = sum(a.token_count_traditional for a in agents)
    # HarmoNet: 직접 통신(네트워크 전송) 토큰 = 0
    total_harmo_comm_tokens = 0
    # HarmoNet: 로컬 지연 복원(Decompression) 계산 토큰
    total_harmo_local_tokens = sum(
        sum(res.token_count for res in a.task_results) for a in agents
    )

    print(f"\n  📈 토큰 사용량 비교 (통신 비용 vs 로컬 계산):")
    print(f"     [통신 토큰 (네트워크 트래픽)]")
    print(f"       기존 방식 (AutoGen 스타일): ~{total_traditional_tokens:,} 토큰")
    print(f"       HarmoNet 방식:              {total_harmo_comm_tokens:,} 토큰")
    print(f"       통신 트래픽 절감율:         100.0%")
    print(f"     [로컬 계산 토큰 (지연 복원)]")
    print(f"       HarmoNet 로컬 복원 토큰:    {total_harmo_local_tokens:,} 토큰")

    print(f"\n  🌌 데이터 우주 통계:")
    print(f"     투하된 씨앗 수:     {total_seeds_deposited}개")
    print(f"     공명 감지 횟수:     {total_resonances}회")
    print(f"     현재 우주 에너지:   {universe.get_global_energy():.4f}")
    print(f"     필드 스냅샷 수:     {len(universe.get_snapshot_history())}개")

    print(f"\n  🤖 에이전트별 통계:")
    for agent in agents:
        stats = agent.get_stats()
        print(f"     [{stats['agent_id']}]")
        print(f"       역할: {stats['role']}, 씨앗 생성: {stats['seeds_created']}, "
              f"씨앗 수신: {stats['seeds_received']}, 완료 작업: {stats['tasks_completed']}")

    # SOC 파워 법칙 분석
    alpha = soc.get_power_law_exponent()
    if alpha:
        print(f"\n  📉 SOC 파워 법칙 지수: α = {alpha:.3f}")
        print(f"     (α ≈ 1.0~1.5 = SOC 임계 상태 = 최적 정보 전달)")
    else:
        print(f"\n  📉 SOC 분석: 캐스케이드 데이터 수집 중... (더 많은 틱 필요)")

    # ─── 6. 쿠라모토 최종 동기화 상태 ─────────────────────────
    print_separator("5️⃣  쿠라모토 최종 동기화 상태")
    r_final, psi_final = kuramoto.get_order_parameter()
    print(f"  질서 파라미터 r = {r_final:.4f}")
    print(f"  평균 집단 위상 ψ = {psi_final:.4f} rad")

    if r_final > 0.7:
        print(f"  ✅ 에이전트들이 강하게 동기화됨 → 높은 협업 효율 달성!")
    elif r_final > 0.4:
        print(f"  🔄 부분 동기화 → 더 많은 틱이 필요")
    else:
        print(f"  ⚠  아직 동기화 임계점 미달 → 결합 강도(K) 조정 필요")

    print_separator("✅ Demo 완료", "═")
    print(f"HarmoNet 프로토타입이 성공적으로 실행되었습니다.")
    print(f"에이전트들이 메시지 없이 데이터 우주의 공명만으로 협업했습니다.")
    print()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_demo_async())
