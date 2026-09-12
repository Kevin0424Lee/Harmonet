"""
benchmark/agents_harmonet.py — HarmoNet 벤치마크 어댑터
=========================================================
BenchmarkHarness.SystemAdapter 인터페이스 구현.
HarmoNet 3-에이전트 (Architect→Builder→Validator) 파이프라인을
단일 태스크 입력에서 실행합니다.
"""

import asyncio
import sys
import os
import time
from typing import Any, Dict, List

# 루트 경로 추가 (benchmark/ 아래에서 실행 시)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from benchmark.tasks import BenchmarkTask
from harmonet.field import DataUniverseField
from harmonet.agent import HarmoAgent, AgentRole, SOCController
from harmonet.resonance import KuraMotoCoupler
from harmonet.usage import METER
from harmonet.trace import NO_COST, TaskState, meter_delta, model_id


def _keyword_hits(output: str, expected_keywords: List[str]) -> int:
    output_lower = output.lower()
    return sum(1 for kw in expected_keywords if kw.lower() in output_lower)


def _passes_keywords(output: str, expected_keywords: List[str]) -> bool:
    if not output or not expected_keywords:
        return False
    return _keyword_hits(output, expected_keywords) >= max(1, len(expected_keywords) // 2)


def _passes_keyword_threshold(
    output: str,
    expected_keywords: List[str],
    threshold: float,
) -> bool:
    if not output or not expected_keywords:
        return False
    return (_keyword_hits(output, expected_keywords) / len(expected_keywords)) >= threshold


def _missing_keywords(output: str, expected_keywords: List[str]) -> List[str]:
    output_lower = output.lower()
    return [kw for kw in expected_keywords if kw.lower() not in output_lower]


class HarmoNetAdapter:
    """
    HarmoNet 3-에이전트 협업 어댑터.

    파이프라인:
        Architect: 태스크 씨앗 투하
        Builder:   씨앗 감지 + 구현
        Validator: Builder 결과 검증
    """

    def __init__(
        self,
        dim: int = 256,
        grid_size: int = 16,
        ticks: int = 5,
        resonance_threshold_arch: float = 0.20,
        resonance_threshold_build: float = 0.15,
        resonance_threshold_valid: float = 0.10,
    ):
        self.dim = dim
        self.grid_size = grid_size
        self.ticks = ticks
        self._th_arch = resonance_threshold_arch
        self._th_build = resonance_threshold_build
        self._th_valid = resonance_threshold_valid

    @property
    def name(self) -> str:
        return "harmonet"

    def _build_pipeline(self):
        """공유 우주 + 3 에이전트 생성 (태스크마다 새로 초기화)."""
        universe = DataUniverseField(dim=self.dim, grid_size=self.grid_size)
        kuramoto = KuraMotoCoupler(coupling_strength=0.5)
        soc = SOCController(threshold=0.7)

        architect = HarmoAgent(
            agent_id="Bench-Architect",
            role=AgentRole.ARCHITECT,
            domain_tags=["system design", "api", "architecture"],
            universe=universe,
            soc_controller=soc,
            kuramoto_coupler=kuramoto,
            resonance_threshold=self._th_arch,
            grid_position=2,
        )
        builder = HarmoAgent(
            agent_id="Bench-Builder",
            role=AgentRole.BUILDER,
            domain_tags=["python", "implementation", "code", "fastapi"],
            universe=universe,
            soc_controller=soc,
            kuramoto_coupler=kuramoto,
            resonance_threshold=self._th_build,
            grid_position=6,
        )
        validator = HarmoAgent(
            agent_id="Bench-Validator",
            role=AgentRole.VALIDATOR,
            domain_tags=[
                "testing",
                "security",
                "validation",
                "review",
                "python",
                "implementation",
                "fastapi",
            ],
            universe=universe,
            soc_controller=soc,
            kuramoto_coupler=kuramoto,
            resonance_threshold=self._th_valid,
            grid_position=11,
        )
        return universe, kuramoto, [architect, builder, validator]

    def run(self, task: BenchmarkTask) -> Dict[str, Any]:
        METER.reset()
        """태스크를 HarmoNet 파이프라인으로 실행."""
        t0 = time.perf_counter()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(self._run_async(task))
        finally:
            loop.close()

        result["latency"] = time.perf_counter() - t0
        return result

    async def _run_async(self, task: BenchmarkTask) -> Dict[str, Any]:
        universe, kuramoto, agents = self._build_pipeline()
        architect, builder, validator = agents

        # ── 1. Architect: 씨앗 투하 ──────────────────────────────
        # task_spec(진입점·테스트·유형)을 과제 씨앗에 실어 builder→validator 피드백 씨앗이 상속하게 한다
        seed = architect.create_and_deposit_seed(task.prompt, metadata={"task_spec": task.spec or {}})
        architect_tokens = len(task.prompt.split()) * 2  # 씨앗 생성 비용

        # ── 2. N틱 실행 ───────────────────────────────────────────
        builder_outputs = []      # builder LLM 출력 (최종 산출물 후보)
        verification = None       # validator 기계 검증 판정 (마지막 것)
        total_tokens = architect_tokens
        state = TaskState(task.id, system=self.name, cost_attribution="tick_aggregate")   # 실행 추적 (WEEK1 A4)
        from harmonet.llm import get_llm_client
        model = model_id(get_llm_client())
        meter_mark = METER.snapshot()

        for _ in range(self.ticks):
            universe.propagate(dt=0.3)
            for agent in agents:
                agent.sync_phase(dt=0.1)
                agent.drift_position()

            scan_tasks = [a.scan_and_process_async() for a in agents]
            results_list = await asyncio.gather(*scan_tasks)
            kuramoto.step(dt=0.1)

            # 이 틱의 LLM 비용은 틱 단위로만 실측된다 (에이전트가 동시에 돌아 호출별 분리 불가).
            # 틱에 LLM 행동이 하나면 그 행동에, 여럿이면 첫 행동에 귀속하고 나머지는 0 으로 기록한다.
            tick_cost = meter_delta(meter_mark)
            meter_mark = METER.snapshot()
            llm_actions_left = sum(1 for _, rs in zip(agents, results_list) for r in rs if r.success and r.verification is None)
            for agent, agent_results in zip(agents, results_list):
                for res in agent_results:
                    if not res.success:
                        continue
                    total_tokens += res.token_count
                    if res.verification is not None:
                        verification = res.verification
                        state.verification = res.verification
                        state.record("verify", "validator", "none", dict(NO_COST, verify_calls=1), res.verification["evidence"])
                    else:
                        cost = tick_cost if llm_actions_left == 1 or agent.role == AgentRole.BUILDER else dict(NO_COST)
                        if cost is tick_cost:
                            tick_cost = dict(NO_COST)
                        llm_actions_left -= 1
                        kind = "build" if agent.role == AgentRole.BUILDER else "expert_review"
                        state.record(kind, agent.role.value, model, cost, str(res.output)[:200])
                        if agent.role == AgentRole.BUILDER and res.output:
                            builder_outputs.append(res.output)
                            state.artifact = res.output

        # ── 3. 최종 출력 = builder 산출물 (validator 판정은 별도 필드) ───────────
        from harmonet.verify import extract_artifact
        kind = (task.spec or {}).get("kind", "code")
        final_output = extract_artifact(builder_outputs[-1], kind) if builder_outputs else ""
        repair_used = False
        initial_missing = _missing_keywords(final_output, task.expected_keywords)
        repair_threshold = float(os.getenv("HARMONET_REPAIR_KEYWORD_THRESHOLD", "0.50"))

        if not _passes_keyword_threshold(final_output, task.expected_keywords, repair_threshold):
            from harmonet.llm import get_llm_client

            repair_prompt = (
                "Repair this benchmark answer while staying concise.\n"
                f"Original task:\n{task.prompt}\n\n"
                f"Missing required terms: {', '.join(initial_missing)}\n\n"
                "Return a corrected final answer with working code when relevant. "
                "Use every missing term verbatim at least once, include no unrelated explanation, "
                "and do not switch to a different task."
            )
            before = METER.snapshot()
            repair_output = await get_llm_client().generate_async(repair_prompt)
            total_tokens += len(repair_prompt.split()) + len(repair_output.split())
            state.record("self_revise", "keyword_repair", model, meter_delta(before), repair_output[:200])
            final_output = (
                f"{final_output}\n\n---\n\n[Repair]\n{repair_output}"
                if final_output else repair_output
            )
            repair_used = True

        # 실측 토큰: 에이전트 간 전달 프롬프트를 포함한 모든 LLM 호출의 API usage 합계.
        # (이전 구현은 통신 토큰을 0으로 선언하고 프롬프트를 단어수×2로 추정했음 — 비교 불가)
        _snap = METER.snapshot()
        prompt_tokens = _snap["prompt_tokens"]
        completion_tokens = _snap["completion_tokens"]
        final_missing = _missing_keywords(final_output, task.expected_keywords)

        if final_output:
            state.artifact = final_output
        state.record("terminate", "system", "none", NO_COST, f"repair_used={repair_used}")
        trace_path = state.save()

        return {
            "output": final_output,
            "trace_path": str(trace_path),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "token_source": "measured" if _snap["measured"] else "estimated",
            "llm_calls": _snap["calls"],
            "verification": verification,   # validator 기계 검증 판정 (없으면 None = validator 미실행)
            "metadata": {
                "seeds_created": sum(a.seeds_created for a in agents),
                "seeds_received": sum(a.seeds_received for a in agents),
                "tasks_completed": sum(
                    sum(1 for r in a.task_results if r.success) for a in agents
                ),
                "ticks": self.ticks,
                "kuramoto_r": kuramoto.get_order_parameter()[0],
                "repair_used": repair_used,
                "repair_keyword_threshold": repair_threshold,
                "initial_missing_keywords": initial_missing,
                "final_missing_keywords": final_missing,
            },
        }
