"""
benchmark/agents_langraph.py — LangGraph 벤치마크 어댑터
=========================================================
LangGraph 1.x API 기반 3-에이전트 (Architect→Builder→Validator)
순차 파이프라인.

HarmoNet과 동일한 태스크를 실행하여 공정한 비교를 제공합니다.

필요 패키지: langgraph >= 1.0, langchain-openai (또는 langchain-anthropic)
API 키: OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 환경변수
"""

import os
import time
from typing import Any, Dict, TypedDict, Annotated, List

from benchmark.tasks import BenchmarkTask

# ── LangGraph 임포트 (없으면 MockAdapter로 폴백) ──────────────────
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    def add_messages(left, right):
        return (left or []) + (right or [])

    _LANGGRAPH_AVAILABLE = False

# ── LLM 임포트 (우선순위: 명시 백엔드 > OpenAI > Anthropic > Ollama > Mock) ──
_LLM_BACKEND = "mock"
_LLM = None
_FORCE_BACKEND = os.environ.get("HARMONET_LLM_BACKEND", "").lower().strip()


def _try_openai():
    global _LLM, _LLM_BACKEND
    try:
        from langchain_openai import ChatOpenAI
        _LLM = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, max_tokens=1024)
        _LLM_BACKEND = "openai"
        return True
    except (ImportError, Exception):
        return False


def _try_anthropic():
    global _LLM, _LLM_BACKEND
    try:
        from langchain_anthropic import ChatAnthropic
        _LLM = ChatAnthropic(model="claude-haiku-4-5", temperature=0.1, max_tokens=1024)
        _LLM_BACKEND = "anthropic"
        return True
    except (ImportError, Exception):
        return False


def _safe_model_slug(model: str) -> str:
    return model.replace("/", "_").replace(":", "_").replace("-", "_")


def _try_runyourai():
    """RunYourAI OpenAI-compatible API backend."""
    global _LLM, _LLM_BACKEND
    api_key = os.environ.get("RUNYOURAI_API_KEY")
    if not api_key:
        return False

    base_url = os.environ.get("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1")
    model = os.environ.get("RUNYOURAI_MODEL", "runyour/free")
    max_tokens = int(os.environ.get("RUNYOURAI_MAX_TOKENS", "1024"))
    temperature = float(os.environ.get("RUNYOURAI_TEMPERATURE", "0.2"))

    try:
        from langchain_openai import ChatOpenAI
        _LLM = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _LLM_BACKEND = f"runyourai_{_safe_model_slug(model)}"
        return True
    except (ImportError, Exception):
        pass

    try:
        from harmonet.llm import RunYourAIClient
        from langchain_core.messages import AIMessage

        class _RunYourAILangChainWrapper:
            def __init__(self):
                self.client = RunYourAIClient(api_key=api_key)

            def invoke(self, messages):
                sys_msg = ""
                prompt_parts = []
                for m in messages:
                    if getattr(m, "type", "") == "system":
                        sys_msg = m.content
                    else:
                        prompt_parts.append(m.content)
                prompt = "\n\n".join(prompt_parts)
                content = self.client.generate(prompt, system_prompt=sys_msg)
                est_in = len(prompt.split()) + len(sys_msg.split())
                est_out = len(content.split())
                resp = AIMessage(content=content)
                resp.usage_metadata = {"input_tokens": est_in, "output_tokens": est_out}
                return resp

        _LLM = _RunYourAILangChainWrapper()
        _LLM_BACKEND = f"runyourai_{_safe_model_slug(model)}_wrapped"
        return True
    except Exception:
        return False


def _try_ollama():
    """로컬 Ollama 서버 감지 후 langchain-ollama 또는 직접 HTTP 클라이언트로 연결."""
    global _LLM, _LLM_BACKEND
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

    # 서버 도달성 확인
    try:
        import requests as _rq
        if not _rq.get(f"{host}/api/tags", timeout=1.5).ok:
            return False
    except Exception:
        return False

    # langchain-ollama가 있으면 사용 (LangGraph 친화적)
    try:
        from langchain_ollama import ChatOllama
        _LLM = ChatOllama(model=model, base_url=host, temperature=0.1)
        _LLM_BACKEND = f"ollama_{model.split(':')[0]}"
        return True
    except ImportError:
        pass

    # 폴백: langchain-community
    try:
        from langchain_community.chat_models import ChatOllama
        _LLM = ChatOllama(model=model, base_url=host, temperature=0.1)
        _LLM_BACKEND = f"ollama_{model.split(':')[0]}"
        return True
    except ImportError:
        pass

    # 최종 폴백: HarmoNet의 OllamaClient를 LangChain 인터페이스로 래핑
    try:
        from harmonet.llm import OllamaClient
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        class _OllamaLangChainWrapper:
            def __init__(self):
                self.client = OllamaClient(host=host, model=model)
            def invoke(self, messages):
                sys_msg = ""
                prompt_parts = []
                for m in messages:
                    if isinstance(m, SystemMessage):
                        sys_msg = m.content
                    else:
                        prompt_parts.append(m.content)
                prompt = "\n\n".join(prompt_parts)
                content = self.client.generate(prompt, system_prompt=sys_msg)
                # tiktoken 없이 단순 추정
                est_in = len(prompt.split()) + len(sys_msg.split())
                est_out = len(content.split())
                resp = AIMessage(content=content)
                resp.usage_metadata = {"input_tokens": est_in, "output_tokens": est_out}
                return resp

        _LLM = _OllamaLangChainWrapper()
        _LLM_BACKEND = f"ollama_{model.split(':')[0]}_wrapped"
        return True
    except Exception:
        return False


# ── 백엔드 선택 ─────────────────────────────────────────────────
if _FORCE_BACKEND == "openai":
    _try_openai()
elif _FORCE_BACKEND == "anthropic":
    _try_anthropic()
elif _FORCE_BACKEND in ("runyourai", "runyour"):
    _try_runyourai()
elif _FORCE_BACKEND == "ollama":
    _try_ollama()
elif _FORCE_BACKEND == "mock":
    pass  # MockLLM 사용
else:
    # 자동 감지
    if os.environ.get("OPENAI_API_KEY"):
        _try_openai()
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _try_anthropic()
    elif os.environ.get("RUNYOURAI_API_KEY"):
        _try_runyourai()
    else:
        _try_ollama()

if _LLM is None:
    # Mock LLM — 실제 API 키 없는 환경에서도 구조 테스트 가능
    class _MockLLM:
        def invoke(self, messages):
            class _R:
                content = (
                    "[MockLLM] No API key set. "
                    "Set OPENAI_API_KEY or ANTHROPIC_API_KEY to use real LLM.\n"
                    "def example_function():\n    pass\n"
                    "# jwt, hmac, sha256, decode, payload, fastapi, pydantic"
                )
                usage_metadata = {"input_tokens": 50, "output_tokens": 50}
            return _R()
    _LLM = _MockLLM()
    _LLM_BACKEND = "mock"


# ── LangGraph State ────────────────────────────────────────────────

class AgentState(TypedDict):
    task: str
    messages: Annotated[List[Any], add_messages]
    architect_output: str
    builder_output: str
    validator_output: str
    total_input_tokens: int
    total_output_tokens: int


# ── 에이전트 노드 함수 ────────────────────────────────────────────

def _architect_node(state: AgentState) -> AgentState:
    from langchain_core.messages import SystemMessage, HumanMessage
    system = SystemMessage(content=(
        "You are an Architect agent. Given a task, design a high-level approach "
        "with key components, data flow, and implementation strategy. Be concise."
    ))
    human = HumanMessage(content=f"Task: {state['task']}")
    result = _LLM.invoke([system, human])
    output = result.content
    usage = getattr(result, "usage_metadata", {}) or {}
    return {
        **state,
        "architect_output": output,
        "messages": [system, human, result],
        "total_input_tokens": state.get("total_input_tokens", 0) + usage.get("input_tokens", len(state["task"].split()) * 2),
        "total_output_tokens": state.get("total_output_tokens", 0) + usage.get("output_tokens", len(output.split())),
    }


def _builder_node(state: AgentState) -> AgentState:
    from langchain_core.messages import SystemMessage, HumanMessage
    context = f"Architect design:\n{state['architect_output']}\n\nOriginal task: {state['task']}"
    system = SystemMessage(content=(
        "You are a Builder agent. Given an architect's design, implement it in Python. "
        "Write working code with type hints and docstrings."
    ))
    human = HumanMessage(content=context)
    result = _LLM.invoke([system, human])
    output = result.content
    usage = getattr(result, "usage_metadata", {}) or {}
    return {
        **state,
        "builder_output": output,
        "messages": state["messages"] + [system, human, result],
        "total_input_tokens": state.get("total_input_tokens", 0) + usage.get("input_tokens", len(context.split()) * 2),
        "total_output_tokens": state.get("total_output_tokens", 0) + usage.get("output_tokens", len(output.split())),
    }


def _validator_node(state: AgentState) -> AgentState:
    from langchain_core.messages import SystemMessage, HumanMessage
    context = (
        f"Original task: {state['task']}\n\n"
        f"Implementation:\n{state['builder_output']}"
    )
    system = SystemMessage(content=(
        "You are a Validator agent. Review the implementation for correctness, "
        "security issues, and edge cases. Suggest improvements if needed."
    ))
    human = HumanMessage(content=context)
    result = _LLM.invoke([system, human])
    output = result.content
    usage = getattr(result, "usage_metadata", {}) or {}
    return {
        **state,
        "validator_output": output,
        "messages": state["messages"] + [system, human, result],
        "total_input_tokens": state.get("total_input_tokens", 0) + usage.get("input_tokens", len(context.split()) * 2),
        "total_output_tokens": state.get("total_output_tokens", 0) + usage.get("output_tokens", len(output.split())),
    }


# ── 그래프 빌드 (최초 1회) ────────────────────────────────────────

def _build_graph():
    if not _LANGGRAPH_AVAILABLE:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("architect", _architect_node)
    graph.add_node("builder", _builder_node)
    graph.add_node("validator", _validator_node)
    graph.set_entry_point("architect")
    graph.add_edge("architect", "builder")
    graph.add_edge("builder", "validator")
    graph.add_edge("validator", END)
    return graph.compile()


_COMPILED_GRAPH = None  # lazy init


# ── 어댑터 ────────────────────────────────────────────────────────

class LangGraphAdapter:
    """
    LangGraph 3-에이전트 파이프라인 어댑터.

    동일한 3단계(설계→구현→검증)를 LangGraph StateGraph로 구현.
    HarmoNet 대비 공정 비교를 위해 동일한 역할 분담 사용.
    """

    @property
    def name(self) -> str:
        return f"langraph_{_LLM_BACKEND}"

    def run(self, task: BenchmarkTask) -> Dict[str, Any]:
        global _COMPILED_GRAPH
        if _COMPILED_GRAPH is None:
            _COMPILED_GRAPH = _build_graph()

        if _COMPILED_GRAPH is None:
            # LangGraph 미설치
            return {
                "output": "[LangGraph 미설치] pip install langgraph langchain-openai",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "metadata": {"backend": "unavailable"},
            }

        initial_state: AgentState = {
            "task": task.prompt,
            "messages": [],
            "architect_output": "",
            "builder_output": "",
            "validator_output": "",
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

        final_state = _COMPILED_GRAPH.invoke(initial_state)

        # 최종 출력 = 검증자 출력 + 빌더 코드
        output = (
            f"[Architect]\n{final_state['architect_output']}\n\n"
            f"[Builder]\n{final_state['builder_output']}\n\n"
            f"[Validator]\n{final_state['validator_output']}"
        )

        return {
            "output": output,
            "prompt_tokens": final_state["total_input_tokens"],
            "completion_tokens": final_state["total_output_tokens"],
            "metadata": {
                "backend": _LLM_BACKEND,
                "architect_tokens": len(final_state["architect_output"].split()),
                "builder_tokens": len(final_state["builder_output"].split()),
                "validator_tokens": len(final_state["validator_output"].split()),
            },
        }
