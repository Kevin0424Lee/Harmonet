"""
CrewAI benchmark adapter.

Uses CrewAI's Agent/Task/Crew primitives over an OpenAI-compatible endpoint.
Backend follows HARMONET_LLM_BACKEND so all systems share one model:
  - openai_compatible : OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_MODEL (e.g. Ollama /v1)
  - runyourai (default): RUNYOURAI_* variables
Token usage is read from harmonet.usage.METER, which the client fills from the
API's `usage` field, so figures are measured rather than estimated.
The workflow is a sequential architect -> builder -> validator chain.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict

from benchmark.tasks import BenchmarkTask
from harmonet.llm import OpenAICompatibleClient, RunYourAIClient
from harmonet.usage import METER


def _count_tokens(text: str) -> int:
    return max(1, int(len((text or "").split()) * 1.3))


def _backend() -> str:
    return os.getenv("HARMONET_LLM_BACKEND", "runyourai").lower().strip()


def _is_compat() -> bool:
    return _backend() in ("openai_compatible", "compat", "ollama_openai")


def _model_name() -> str:
    if _is_compat():
        return os.getenv("OPENAI_COMPAT_MODEL", "qwen2.5:7b")
    return os.getenv("RUNYOURAI_MODEL", "anthropic/claude-haiku-4-5")


def _base_url() -> str:
    if _is_compat():
        return os.getenv("OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1")
    return os.getenv("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1")


def _make_client():
    """HarmoNet과 동일한 OpenAI 호환 클라이언트. usage를 METER에 실측 기록한다."""
    if _is_compat():
        return OpenAICompatibleClient(
            api_key=os.getenv("OPENAI_COMPAT_API_KEY", "ollama"),
            base_url=_base_url(),
            model=_model_name(),
            temperature=float(os.getenv("OPENAI_COMPAT_TEMPERATURE", "0.2")),
            timeout=float(os.getenv("OPENAI_COMPAT_TIMEOUT_SECONDS", "300")),
            max_tokens=int(os.getenv("OPENAI_COMPAT_MAX_TOKENS", "1024")),
            label="OpenAI-Compatible",
        )
    api_key = os.getenv("RUNYOURAI_API_KEY")
    if not api_key:
        raise RuntimeError("RUNYOURAI_API_KEY is required for CrewAIAdapter")
    return RunYourAIClient(api_key=api_key)


def _is_unified_diff_task(prompt: str) -> bool:
    marker = (prompt or "").lower()
    return "unified diff" in marker or "diff --git" in marker or "swe-bench" in marker


class CrewAIAdapter:
    @property
    def name(self) -> str:
        model = _model_name().replace("/", "_").replace("-", "_").replace(":", "_")
        return f"crewai_{model}"

    def run(self, task: BenchmarkTask) -> Dict[str, Any]:
        from crewai import Agent, Crew, Process, Task
        from crewai.llms.base_llm import BaseLLM

        os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
        os.environ.setdefault("OTEL_SDK_DISABLED", "true")

        class RunYourCrewLLM(BaseLLM):
            def __init__(self):
                client = _make_client()
                super().__init__(
                    model=client.model,
                    temperature=client.temperature,
                    api_key=client.api_key,
                    base_url=client.base_url,
                    provider="openai_compatible" if _is_compat() else "runyourai",
                )
                self.client = client

            def call(
                self,
                messages,
                tools=None,
                callbacks=None,
                available_functions=None,
                from_task=None,
                from_agent=None,
                response_model=None,
            ):
                system = ""
                parts = []
                if isinstance(messages, str):
                    parts.append(messages)
                else:
                    for msg in messages:
                        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
                        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
                        if role == "system":
                            system += f"\n{content}"
                        else:
                            parts.append(str(content))
                prompt = "\n\n".join(parts)
                return self.client.generate(prompt, system_prompt=system.strip() or None)

        t0 = time.perf_counter()
        METER.reset()  # 이 run()의 LLM 호출만 집계
        llm = RunYourCrewLLM()
        wants_patch = _is_unified_diff_task(task.prompt)
        if wants_patch:
            architect_goal = "Create concise repair plans for repository patch tasks."
            builder_goal = "Write minimal valid unified diffs that apply to the base repository."
            validator_goal = "Finalize valid unified diffs without commentary or markdown fences."
            build_instruction = "Return only a valid unified diff. Do not use markdown fences. Do not explain."
            final_instruction = "Fix any issue and return only the final unified diff."
            build_expected = "A valid unified diff patch."
            final_expected = "Final unified diff only."
        else:
            architect_goal = "Create concise implementation plans for Python coding tasks."
            builder_goal = "Write executable Python code that satisfies tests."
            validator_goal = "Finalize Python code for automated tests."
            build_instruction = "Return complete executable Python code only."
            final_instruction = "Fix any issue and return only final Python code."
            build_expected = "Complete Python code."
            final_expected = "Final Python code only."

        architect = Agent(
            role="Architect",
            goal=architect_goal,
            backstory="Senior Python architect focused on benchmark constraints.",
            llm=llm,
            verbose=False,
            allow_delegation=False,
            max_iter=1,
        )
        builder = Agent(
            role="Builder",
            goal=builder_goal,
            backstory="Pragmatic engineer who returns exactly the requested artifact.",
            llm=llm,
            verbose=False,
            allow_delegation=False,
            max_iter=1,
        )
        validator = Agent(
            role="Validator",
            goal=validator_goal,
            backstory="Strict reviewer who preserves benchmark output constraints.",
            llm=llm,
            verbose=False,
            allow_delegation=False,
            max_iter=1,
        )

        t_plan = Task(
            description=f"Task:\n{task.prompt}\n\nReturn only the minimal plan and constraints.",
            expected_output="A concise implementation plan.",
            agent=architect,
        )
        t_build = Task(
            description=(
                f"Task:\n{task.prompt}\n\nUse the architect plan. "
                f"{build_instruction}"
            ),
            expected_output=build_expected,
            agent=builder,
            context=[t_plan],
        )
        t_validate = Task(
            description=(
                f"Original task:\n{task.prompt}\n\nReview the candidate code from context. "
                f"{final_instruction}"
            ),
            expected_output=final_expected,
            agent=validator,
            context=[t_build],
        )

        crew = Crew(
            agents=[architect, builder, validator],
            tasks=[t_plan, t_build, t_validate],
            process=Process.sequential,
            verbose=False,
            memory=False,
        )
        result = crew.kickoff()
        output = str(result)

        # 커스텀 BaseLLM은 crew.usage_metrics를 채우지 않으므로, 클라이언트가 API usage로
        # 기록한 METER를 쓴다. usage 미제공 응답이 하나라도 있으면 estimated로 표시된다.
        snap = METER.snapshot()
        prompt_tokens = snap["prompt_tokens"]
        completion_tokens = snap["completion_tokens"]
        token_source = "measured" if snap["measured"] and snap["calls"] > 0 else "estimated"
        if prompt_tokens <= 0 and completion_tokens <= 0:
            prompt_tokens = _count_tokens(task.prompt) * 3
            completion_tokens = _count_tokens(output)
            token_source = "estimated"

        return {
            "output": output,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "token_source": token_source,
            "llm_calls": snap["calls"],
            "metadata": {
                "framework": "crewai",
                "model": _model_name(),
                "backend": _backend(),
                "calls": snap["calls"],
                "elapsed_adapter_s": round(time.perf_counter() - t0, 4),
            },
        }
