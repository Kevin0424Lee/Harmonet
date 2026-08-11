"""
demo_distributed.py — 멀티프로세스 분산 협업 데모
===================================================
2개의 독립 Python 프로세스가 동일 Redis(또는 로컬 인메모리 폴백)를 통해
씨앗을 공유하고, cross-process 공명을 검증합니다.

Redis가 실행 중이면 진짜 분산 동작 검증.
Redis가 없으면 로컬 폴백으로 시뮬레이션합니다.

실행 방법:
    python -X utf8 demo_distributed.py

내부 동작:
    1. 부모 프로세스가 workerA / workerB 를 subprocess로 기동
    2. workerA: Architect 에이전트 → 씨앗 투하 후 3-tick 실행
    3. workerB: Builder 에이전트  → 씨앗 감지 및 공명 처리
    4. 부모 프로세스가 두 워커 완료 후 결과 합산
"""

import sys
import os
import time
import json
import asyncio
import multiprocessing
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── 워커 함수 ─────────────────────────────────────────────────────

def worker_architect(result_path: str, redis_available: bool) -> None:
    """워커 A: Architect 에이전트 — 씨앗 투하."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from harmonet.field import DataUniverseField
    from harmonet.agent import HarmoAgent, AgentRole, SOCController
    from harmonet.resonance import KuraMotoCoupler

    print("[Worker-A] Architect 프로세스 시작 (PID={})".format(os.getpid()))

    universe  = DataUniverseField(dim=64, grid_size=8)
    kuramoto  = KuraMotoCoupler(coupling_strength=0.5)
    soc       = SOCController(threshold=0.8)

    architect = HarmoAgent(
        agent_id="Distributed-Architect",
        role=AgentRole.ARCHITECT,
        domain_tags=["api design", "jwt authentication", "restful"],
        universe=universe,
        soc_controller=soc,
        kuramoto_coupler=kuramoto,
        resonance_threshold=0.20,
        grid_position=2,
    )

    # 씨앗 투하
    task = "Design a secure JWT authentication API with signup, login, refresh token endpoints."
    seed = architect.create_and_deposit_seed(task)
    print(f"[Worker-A] 씨앗 투하 완료: {seed.id[:12]}...")
    print(f"[Worker-A] Redis 저장: {universe.store.is_active}")

    # 3-tick 실행 후 종료
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        for tick in range(1, 4):
            universe.propagate(dt=0.3)
            architect.sync_phase(dt=0.1)
            architect.drift_position()
            results = await architect.scan_and_process_async()
            r_val, _ = kuramoto.get_order_parameter()
            print(f"[Worker-A] Tick {tick} | r={r_val:.3f} | 공명={len(results)}회")
            await asyncio.sleep(0.1)

    loop.run_until_complete(run())
    loop.close()

    result = {
        "worker": "Architect",
        "pid": os.getpid(),
        "seed_id": seed.id,
        "seeds_created": architect.seeds_created,
        "seeds_received": architect.seeds_received,
        "tasks_completed": sum(1 for r in architect.task_results if r.success),
        "redis_active": universe.store.is_active,
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(f"[Worker-A] 완료 → {result_path}")


def worker_builder(seed_id_hint: str, result_path: str, redis_available: bool) -> None:
    """워커 B: Builder 에이전트 — cross-process 씨앗 공명 감지."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    import time as _t
    from harmonet.field import DataUniverseField
    from harmonet.agent import HarmoAgent, AgentRole, SOCController
    from harmonet.resonance import KuraMotoCoupler

    print("[Worker-B] Builder 프로세스 시작 (PID={})".format(os.getpid()))

    # Worker-A와 동일한 Redis namespace에 연결
    universe  = DataUniverseField(dim=64, grid_size=8)
    kuramoto  = KuraMotoCoupler(coupling_strength=0.5)
    soc       = SOCController(threshold=0.8)

    builder = HarmoAgent(
        agent_id="Distributed-Builder",
        role=AgentRole.BUILDER,
        domain_tags=["fastapi", "python", "jwt", "authentication"],
        universe=universe,
        soc_controller=soc,
        kuramoto_coupler=kuramoto,
        resonance_threshold=0.15,
        grid_position=5,
    )

    print(f"[Worker-B] Redis 연결: {universe.store.is_active}")

    # Redis 활성 시 Worker-A의 씨앗이 동기화될 때까지 잠시 대기
    if universe.store.is_active:
        print("[Worker-B] Redis 씨앗 동기화 대기 중 (최대 3초)...")
        for _ in range(30):
            synced = universe.sync_seed_registry_from_store()
            if synced > 0 or seed_id_hint in universe.seed_registry:
                print(f"[Worker-B] 씨앗 동기화 완료 ({synced}개 신규)")
                break
            _t.sleep(0.1)
    else:
        # 폴백: Worker-A의 씨앗 정보를 직접 가져올 수 없으므로
        # 공유 인메모리 불가 → 자체 씨앗 투하로 시뮬레이션
        print("[Worker-B] Redis 없음 — 로컬 폴백 모드 (자체 씨앗으로 시뮬레이션)")
        builder.create_and_deposit_seed(
            "Implement JWT auth FastAPI endpoints based on architect's design."
        )

    # 3-tick 실행
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    cross_process_resonances = 0

    async def run():
        nonlocal cross_process_resonances
        for tick in range(1, 4):
            universe.propagate(dt=0.3)
            builder.sync_phase(dt=0.1)
            builder.drift_position()
            results = await builder.scan_and_process_async()

            # cross-process 공명: Distributed-Architect가 만든 씨앗을 감지한 경우
            for res in results:
                if "Architect" in res.seed_id or seed_id_hint[:8] in res.seed_id:
                    cross_process_resonances += 1
            # 더 넓게: 우리 자신이 만들지 않은 씨앗을 처리했다면 cross-process
            cross_process_resonances += sum(
                1 for ev in builder.detector.resonance_history[-len(results):]
                if ev.seed.creator_id == "Distributed-Architect"
            )

            r_val, _ = kuramoto.get_order_parameter()
            print(f"[Worker-B] Tick {tick} | r={r_val:.3f} | 공명={len(results)}회 | "
                  f"cross-process={cross_process_resonances}회")
            await asyncio.sleep(0.1)

    loop.run_until_complete(run())
    loop.close()

    # cross-process 공명 감지 여부 (resonance_history 전체 스캔)
    cross_detections = sum(
        1 for ev in builder.detector.resonance_history
        if ev.seed.creator_id == "Distributed-Architect"
    )

    result = {
        "worker": "Builder",
        "pid": os.getpid(),
        "seeds_created": builder.seeds_created,
        "seeds_received": builder.seeds_received,
        "tasks_completed": sum(1 for r in builder.task_results if r.success),
        "cross_process_resonances": cross_detections,
        "redis_active": universe.store.is_active,
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(f"[Worker-B] 완료 → {result_path}")


# ── 메인 ─────────────────────────────────────────────────────────

def print_sep(title: str = "", width: int = 72, char: str = "─"):
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{char * pad} {title} {char * pad}")
    else:
        print(char * width)


def main():
    print_sep("HarmoNet 멀티프로세스 분산 협업 데모", char="═")

    # Redis 가용성 확인
    redis_available = False
    try:
        import redis as _redis
        r = _redis.Redis(host="localhost", port=6379, socket_connect_timeout=0.5)
        r.ping()
        redis_available = True
        print("[Main] Redis 서버 감지 → 진짜 분산 모드")
    except Exception:
        print("[Main] Redis 없음 → 로컬 폴백 모드 (각 프로세스 독립 메모리)")

    print(f"[Main] Python PID: {os.getpid()}")
    print_sep()

    # 임시 결과 파일 경로
    with tempfile.NamedTemporaryFile(suffix="_architect.json", delete=False) as fa:
        path_a = fa.name
    with tempfile.NamedTemporaryFile(suffix="_builder.json", delete=False) as fb:
        path_b = fb.name

    # Worker-A 먼저 기동 (씨앗 투하)
    print("\n[Main] Worker-A (Architect) 기동...")
    proc_a = multiprocessing.Process(
        target=worker_architect,
        args=(path_a, redis_available),
        daemon=False,
    )
    proc_a.start()

    # Redis 모드면 씨앗이 Redis에 저장될 시간 대기
    if redis_available:
        time.sleep(0.5)

    # Worker-B 기동 (Builder)
    print("[Main] Worker-B (Builder) 기동...")
    proc_b = multiprocessing.Process(
        target=worker_builder,
        args=("", path_b, redis_available),
        daemon=False,
    )
    proc_b.start()

    # 두 워커 완료 대기
    proc_a.join(timeout=60)
    proc_b.join(timeout=60)

    # 결과 수집
    print_sep("분산 협업 결과")

    result_a = result_b = {}
    try:
        with open(path_a, encoding="utf-8") as f:
            result_a = json.load(f)
    except Exception as e:
        print(f"[Main] Worker-A 결과 로드 실패: {e}")

    try:
        with open(path_b, encoding="utf-8") as f:
            result_b = json.load(f)
    except Exception as e:
        print(f"[Main] Worker-B 결과 로드 실패: {e}")

    # 정리
    for p in [path_a, path_b]:
        try:
            os.unlink(p)
        except Exception:
            pass

    print(f"\n  Worker-A (Architect) PID={result_a.get('pid', '?')}")
    print(f"    씨앗 생성:   {result_a.get('seeds_created', '?')}개")
    print(f"    작업 완료:   {result_a.get('tasks_completed', '?')}건")
    print(f"    Redis 활성:  {result_a.get('redis_active', '?')}")

    print(f"\n  Worker-B (Builder)   PID={result_b.get('pid', '?')}")
    print(f"    씨앗 수신:   {result_b.get('seeds_received', '?')}개")
    print(f"    작업 완료:   {result_b.get('tasks_completed', '?')}건")
    cross = result_b.get('cross_process_resonances', 0)
    print(f"    Cross-process 공명: {cross}회")

    print_sep()
    if redis_available and cross > 0:
        print("✅ 진짜 분산 검증 성공: Redis를 통해 cross-process 공명 감지됨")
    elif not redis_available:
        print("✅ 로컬 폴백 모드 완료")
        print("   → Redis 기동 후 재실행 시 진짜 cross-process 공명 검증 가능")
        print("   → 명령: redis-server (별도 터미널)")
    else:
        print("⚠  Cross-process 공명 미감지 — 씨앗 동기화 타이밍 조정 필요")

    print_sep("완료", char="═")


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
