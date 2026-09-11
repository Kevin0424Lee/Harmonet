"""
AutoGen benchmark adapter.

Uses Microsoft AutoGen AgentChat over an OpenAI-compatible endpoint.
Backend follows HARMONET_LLM_BACKEND so all systems share one model:
  - openai_compatible : OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_MODEL (e.g. Ollama /v1)
  - runyourai (default): RUNYOURAI_* variables
Token usage comes from OpenAIChatCompletionClient.total_usage(), which AutoGen
accumulates from the API's `usage` field (measured, not estimated).
The adapter executes a compact three-agent pipeline:
architect -> builder -> validator/finalizer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List

from benchmark.tasks import BenchmarkTask


def _count_tokens(text: str) -> int:
    return max(1, int(len((text or "").split()) * 1.3))


def _quiet_autogen_logs() -> None:
    noisy_loggers = [
        "autogen_core",
        "autogen_core.events",
        "autogen_core.trace",
        "autogen_agentchat",
        "autogen_ext",
    ]
    for name in noisy_loggers:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)
        logger.propagate = False


def _backend() -> str:
    return os.getenv("HARMONET_LLM_BACKEND", "runyourai").lower().strip()


def _is_compat() -> bool:
    return _backend() in ("openai_compatible", "compat", "ollama_openai")


def _model_name() -> str:
    if _is_compat():
        return os.getenv("OPENAI_COMPAT_MODEL", "qwen2.5:7b")
    return os.getenv("RUNYOURAI_MODEL", "anthropic/claude-haiku-4-5")


def _model_config() -> Dict[str, Any]:
    if _is_compat():
        # HarmoNet / CrewAI / LangGraph와 같은 OPENAI_COMPAT_* 설정
        conn = {
            "model": _model_name(),
            "api_key": os.getenv("OPENAI_COMPAT_API_KEY", "ollama"),
            "base_url": os.getenv("OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1"),
            "temperature": float(os.getenv("OPENAI_COMPAT_TEMPERATURE", "0.2")),
            "max_tokens": int(os.getenv("OPENAI_COMPAT_MAX_TOKENS", "1024")),
            "timeout": float(os.getenv("OPENAI_COMPAT_TIMEOUT_SECONDS", "300")),
        }
    else:
        conn = {
            "model": _model_name(),
            "api_key": os.getenv("RUNYOURAI_API_KEY"),
            "base_url": os.getenv("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1"),
            "temperature": float(os.getenv("RUNYOURAI_TEMPERATURE", "0.2")),
            "max_tokens": int(os.getenv("RUNYOURAI_MAX_TOKENS", "1024")),
        }
    return {
        **conn,
        "model_info": {
            "vision": False,
            "function_calling": False,
            "json_output": False,
            "family": "unknown",
            "structured_output": False,
        },
    }


def _last_text(result: Any) -> str:
    messages = getattr(result, "messages", None) or []
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if isinstance(content, str) and content.strip():
            return content
    return str(result)


class AutoGenAdapter:
    @property
    def name(self) -> str:
        model = _model_name().replace("/", "_").replace("-", "_").replace(":", "_")
        return f"autogen_{model}"

    def run(self, task: BenchmarkTask) -> Dict[str, Any]:
        t0 = time.perf_counter()
        result = asyncio.run(self._run_async(task))
        result["metadata"]["elapsed_adapter_s"] = round(time.perf_counter() - t0, 4)
        return result

    async def _run_async(self, task: BenchmarkTask) -> Dict[str, Any]:
        _quiet_autogen_logs()
        from autogen_agentchat.agents import AssistantAgent
        from autogen_ext.models.openai import OpenAIChatCompletionClient

        cfg = _model_config()
        if not cfg["api_key"]:
            raise RuntimeError("API key is required for AutoGenAdapter "
                               "(RUNYOURAI_API_KEY, or OPENAI_COMPAT_API_KEY when openai_compatible)")

        clients = [OpenAIChatCompletionClient(**cfg) for _ in range(3)]
        architect = AssistantAgent(
            "architect",
            clients[0],
            system_message=(
                "You design concise implementation plans for Python coding benchmark tasks. "
                "Return only essential constraints and edge cases."
            ),
        )
        builder = AssistantAgent(
            "builder",
            clients[1],
            system_message=(
                "You implement Python benchmark tasks. Return complete executable Python code, "
                "preferably one code block, with no unrelated prose."
            ),
        )
        validator = AssistantAgent(
            "validator",
            clients[2],
            system_message=(
                "You finalize Python code for automated benchmark tests. Preserve the required "
                "function name and return only final Python code."
            ),
        )

        plan_result = await architect.run(task=f"Task:\n{task.prompt}")
        plan = _last_text(plan_result)
        build_prompt = f"Task:\n{task.prompt}\n\nPlan:\n{plan}\n\nReturn final code."
        code_result = await builder.run(task=build_prompt)
        code = _last_text(code_result)
        final_prompt = (
            f"Original task:\n{task.prompt}\n\nCandidate code:\n{code}\n\n"
            "Fix any issue and return only final Python code."
        )
        final_result = await validator.run(task=final_prompt)
        final = _last_text(final_result)

        # 실측: AutoGen 클라이언트가 API 응답 usage를 누적한 값. (이전 구현은 단어수×1.3 추정)
        prompt_tokens = 0
        completion_tokens = 0
        for client in clients:
            u = client.total_usage()
            prompt_tokens += int(getattr(u, "prompt_tokens", 0) or 0)
            completion_tokens += int(getattr(u, "completion_tokens", 0) or 0)
        token_source = "measured"
        if prompt_tokens <= 0 and completion_tokens <= 0:
            # 엔드포인트가 usage를 생략한 경우에만 추정치로 폴백
            prompt_tokens = _count_tokens(task.prompt + plan + build_prompt + final_prompt)
            completion_tokens = _count_tokens(plan + code + final)
            token_source = "estimated"

        for client in clients:
            close = getattr(client, "close", None)
            if close:
                await close()

        return {
            "output": f"[Architect]\n{plan}\n\n[Builder]\n{code}\n\n[Validator]\n{final}",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "token_source": token_source,
            "llm_calls": 3,
            "metadata": {
                "framework": "autogen",
                "model": cfg["model"],
                "backend": _backend(),
                "calls": 3,
            },
        }
