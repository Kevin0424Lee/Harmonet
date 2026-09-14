"""
LLM Connector for HarmoNet
==========================
실제 LLM(OpenAI, Anthropic, Ollama) 연동 및 테스트를 위한 Mock LLM 지원 모듈.

개선 사항:
- get_llm_client() 싱글턴: 매 씨앗 처리마다 클라이언트 재생성 방지
- OpenAI AsyncOpenAI / Anthropic AsyncAnthropic 사용으로 진짜 비동기 처리
  (기존 asyncio.to_thread는 스레드 풀을 낭비하고 이벤트 루프 블로킹 우회에 불과)
- 지수 백오프 재시도 (속도 제한·일시적 서버 오류 자동 복구)
- Anthropic 프롬프트 캐싱 (cache_control: ephemeral) — 긴 시스템 프롬프트 반복 비용 절감
"""

import os
import time as _time
import functools
import asyncio as _asyncio
from abc import ABC, abstractmethod
from typing import Dict, Optional

# ── 지수 백오프 재시도 유틸리티 ────────────────────────────────

_RETRYABLE_KEYWORDS = ("rate_limit", "rate limit", "429", "503", "timeout", "overloaded")

def _is_retryable(exc: Exception) -> bool:
    return any(kw in str(exc).lower() for kw in _RETRYABLE_KEYWORDS)

def _retry_sync(max_retries: int = 3, base_delay: float = 1.0):
    """동기 메서드용 지수 백오프 재시도 데코레이터."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if _is_retryable(exc) and attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"[LLM] 재시도 {attempt+1}/{max_retries} "
                              f"({delay:.1f}s 대기): {str(exc)[:80]}")
                        _time.sleep(delay)
                    else:
                        raise
        return wrapper
    return decorator

async def _call_with_async_retry(coro_factory, max_retries: int = 3, base_delay: float = 1.0):
    """비동기 코루틴 팩토리에 지수 백오프 재시도를 적용."""
    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except Exception as exc:
            if _is_retryable(exc) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"[LLM] 비동기 재시도 {attempt+1}/{max_retries} "
                      f"({delay:.1f}s 대기): {str(exc)[:80]}")
                await _asyncio.sleep(delay)
            else:
                raise

# LLM 클라이언트 싱글턴 — get_llm_client() 최초 호출 시 생성 후 재사용
_llm_client_singleton: Optional["LLMClient"] = None

from .usage import METER


def _est_tokens(text: str) -> int:
    """usage 미제공 백엔드용 폴백 추정 (문자수/4). 추정임이 계측기에 표시된다."""
    return max(1, len(text or "") // 4)



class LLMClient(ABC):
    """LLM 클라이언트 인터페이스"""
    role: str = "default"   # 역할별 클라이언트(get_llm_client(role)) 가 설정. METER 집계 태그 (WEEK1 A5)
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass

    @abstractmethod
    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass



class MockLLMClient(LLMClient):
    """API 키가 없을 때 작동하는 하이브리드 Mock LLM"""

    def __init__(self, model: str = "mock"):
        self.model = model   # HARMONET_MODEL_BUILDER=mock-a 같은 설정명을 그대로 echo (trace 에서 역할 구분용)
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        # 간단한 휴리스틱 매칭으로 실제 LLM이 생성한 것 같은 고품질 코드 출력 반환
        prompt_lower = prompt.lower()
        
        # 1. API Design Task
        if "design a restful api" in prompt_lower or "api design" in prompt_lower:
            return """# FastAPI Authentication API Specification
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

app = FastAPI(title="HarmoNet Auth Service", version="1.0.0")

class UserLogin(BaseModel):
    email: EmailStr
    password: str

@app.post("/auth/login", status_code=status.HTTP_200_OK)
def login(user: UserLogin):
    # JWT 발행 및 검증 규칙 적용
    return {"access_token": "mock-jwt-token-xyz", "token_type": "bearer"}

@app.post("/auth/refresh")
def refresh():
    return {"access_token": "new-mock-jwt-token-abc"}

@app.delete("/auth/logout")
def logout():
    return {"message": "Logged out successfully"}
"""
        
        # 2. Implementation Task
        elif "implement" in prompt_lower or "fastapi" in prompt_lower:
            return """# FastAPI Implementation of Auth Service with Redis & JWT
import jwt
import bcrypt
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, status

SECRET_KEY = "harmonet-quantum-key-entanglement"
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
"""

        # 3. Data Models Task
        elif "data models" in prompt_lower or "pydantic" in prompt_lower:
            return """# Pydantic v2 Data Models
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

class User(BaseModel):
    id: int
    email: EmailStr
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Token(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 3600
    token_type: str = "bearer"
"""

        # 4. Validation/Security Task
        elif "validate" in prompt_lower or "security" in prompt_lower or "owasp" in prompt_lower:
            return """# Security Audit Report (OWASP Top 10 Reference)
1. JWT Invalidation check:
   - Logout endpoint invalidates tokens on Redis blacklist. (PASSED)
2. Password Hashing:
   - Used Bcrypt with work factor 12. (PASSED)
3. Rate Limiting:
   - Redis rate limiter restricts endpoint to 10 req/min. (PASSED)
4. Session Management:
   - HTTPOnly cookies enforced for cookies token. (PASSED)
   
Overall Status: ✅ SECURE
"""

        # 기본 응답
        return f"[MockLLM] Expanded instruction successfully: {prompt[:120]}..."

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        import asyncio
        # 실제 API 지연을 흉내내기 위해 비동기 sleep을 추가 (틱 블로킹 방지 확인용)
        await asyncio.sleep(0.5)
        return self.generate(prompt, system_prompt)



class OpenAIClient(LLMClient):
    """OpenAI API 연동 클라이언트 (동기 + 진짜 비동기, 지수 백오프 재시도)"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is missing.")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        from openai import OpenAI, AsyncOpenAI
        self.client = OpenAI(api_key=self.api_key)
        # AsyncOpenAI: 스레드 풀 없이 이벤트 루프에서 직접 비동기 처리
        self.async_client = AsyncOpenAI(api_key=self.api_key)

    @_retry_sync(max_retries=3, base_delay=1.0)
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
        )
        METER.record_from_response(response, role=self.role)
        return response.choices[0].message.content

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """AsyncOpenAI로 이벤트 루프 블로킹 없이 진짜 비동기 처리 (지수 백오프 재시도)"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async def _call():
            return await self.async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )

        response = await _call_with_async_retry(_call)
        METER.record_from_response(response, role=self.role)
        return response.choices[0].message.content



class OpenAICompatibleClient(LLMClient):
    """OpenAI-compatible chat completions client for routed providers."""

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        model: str,
        temperature: float = 0.2,
        timeout: float = 120.0,
        max_tokens: int | None = 1024,
        label: str = "openai-compatible",
    ):
        if not api_key:
            raise ValueError(f"{label} API key is missing.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.label = label
        from openai import OpenAI, AsyncOpenAI
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        self.async_client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )

    def _chat_kwargs(self, messages):
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        return kwargs

    @_retry_sync(max_retries=3, base_delay=2.0)
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat.completions.create(**self._chat_kwargs(messages))
        METER.record_from_response(response, role=self.role)
        return response.choices[0].message.content or ""

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async def _call():
            return await self.async_client.chat.completions.create(
                **self._chat_kwargs(messages)
            )

        response = await _call_with_async_retry(_call, base_delay=2.0)
        METER.record_from_response(response, role=self.role)
        return response.choices[0].message.content or ""


class RunYourAIClient(OpenAICompatibleClient):
    """RunYourAI API router client using its OpenAI-compatible endpoint."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        max_tokens = os.getenv("RUNYOURAI_MAX_TOKENS")
        super().__init__(
            api_key=api_key or os.getenv("RUNYOURAI_API_KEY"),
            base_url=os.getenv("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1"),
            model=model or os.getenv("RUNYOURAI_MODEL", "runyour/free"),
            temperature=float(os.getenv("RUNYOURAI_TEMPERATURE", "0.2")),
            timeout=float(os.getenv("RUNYOURAI_TIMEOUT_SECONDS", "120")),
            max_tokens=int(max_tokens) if max_tokens else 1024,
            label="RunYourAI",
        )


class AnthropicClient(LLMClient):
    """
    Anthropic Claude API 연동 클라이언트 (동기 + 진짜 비동기, 프롬프트 캐싱, 지수 백오프).

    프롬프트 캐싱:
    - 시스템 프롬프트에 cache_control: {"type": "ephemeral"} 적용
    - 반복 호출 시 입력 토큰 비용 ~90% 절감 (캐시 히트 시 0.1× 요금)
    """

    # 모든 에이전트가 공유하는 기본 시스템 프롬프트 — 길이가 길수록 캐싱 효과 극대화
    _DEFAULT_SYSTEM = (
        "You are a HarmoNet collaborative AI agent operating in a resonance-triggered "
        "seed coding protocol. You receive compressed seed formulas from the shared data "
        "universe field and decompress them into high-quality, production-ready code outputs. "
        "Always produce complete, functional implementations with proper error handling."
    )

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key is missing.")
        # 모델·생성 파라미터는 환경변수로 조정 가능 (벤치마크에서 다른 백엔드와 조건을 맞추기 위함)
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        self.max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "2048"))
        _t = os.getenv("ANTHROPIC_TEMPERATURE")
        self.temperature = float(_t) if _t else None  # None이면 API 기본값
        from anthropic import Anthropic, AsyncAnthropic
        self.client = Anthropic(api_key=self.api_key)
        # AsyncAnthropic: httpx 기반 진짜 비동기 — asyncio.to_thread 불필요
        self.async_client = AsyncAnthropic(api_key=self.api_key)

    def _build_system_blocks(self, system_prompt: Optional[str] = None):
        """cache_control이 적용된 시스템 프롬프트 블록 생성."""
        text = system_prompt if system_prompt else self._DEFAULT_SYSTEM
        # ephemeral 캐시: TTL 5분, 반복 호출 시 입력 토큰 절감
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def count_input_tokens(self, prompt: str, system_prompt: Optional[str] = None) -> int:
        """무료 count_tokens 엔드포인트로 입력 토큰을 센다 (Week2-F2 예산 예약용). 실패는 예외로 — 추정으로 대체하지 않는다."""
        kw = self._msg_kwargs(prompt, self._build_system_blocks(system_prompt))
        r = self.client.messages.count_tokens(model=kw["model"], system=kw["system"], messages=kw["messages"])
        return int(r.input_tokens)

    @_retry_sync(max_retries=3, base_delay=2.0)
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        response = self.client.messages.create(**self._msg_kwargs(prompt, self._build_system_blocks(system_prompt)))
        METER.record_from_response(response, role=self.role)
        return response.content[0].text

    def _msg_kwargs(self, prompt: str, system_blocks) -> dict:
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_blocks,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.temperature is not None:
            # anthropic SDK 1.x는 temperature를 명명 인자로 받지 않는다 (4.6+ 모델에서 제거된 파라미터).
            # Haiku 4.5 등 지원 모델에 한해 extra_body로 전달한다.
            kwargs["extra_body"] = {"temperature": self.temperature}
        return kwargs

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """AsyncAnthropic으로 이벤트 루프 블로킹 없이 진짜 비동기 처리 (지수 백오프 재시도)."""
        system_blocks = self._build_system_blocks(system_prompt)

        async def _call():
            return await self.async_client.messages.create(**self._msg_kwargs(prompt, system_blocks))

        response = await _call_with_async_retry(_call, base_delay=2.0)
        METER.record_from_response(response, role=self.role)
        return response.content[0].text



class OllamaClient(LLMClient):
    """
    로컬 Ollama 서버 연동 클라이언트.

    환경변수:
        OLLAMA_HOST            기본 http://localhost:11434
        OLLAMA_MODEL           기본 llama3.1:8b
        OLLAMA_TIMEOUT_SECONDS 기본 120 (로컬 추론 지연 고려)
        OLLAMA_TEMPERATURE     기본 0.2

    Linux 설치:
        curl -fsSL https://ollama.com/install.sh | sh
        ollama pull llama3.1:8b      # 또는 qwen2.5:7b, mistral:7b
        ollama serve                  # 백그라운드 실행
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.1:8b",
        timeout: float | None = None,
        temperature: float | None = None,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout or float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
        self.temperature = temperature if temperature is not None else float(
            os.getenv("OLLAMA_TEMPERATURE", "0.2")
        )
        num_predict = os.getenv("OLLAMA_NUM_PREDICT")
        self.num_predict = int(num_predict) if num_predict else None
        import requests
        self.requests = requests
        # 비동기용 클라이언트 (httpx)
        try:
            import httpx
            self._httpx = httpx
        except ImportError:
            self._httpx = None

    @_retry_sync(max_retries=3, base_delay=2.0)
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        url = f"{self.host}/api/generate"
        options = {"temperature": self.temperature}
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt or "",
            "stream": False,
            "options": options,
        }
        response = self.requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        # Ollama는 모델 토크나이저 기준 실제 토큰 수를 반환한다 (추정치가 아님)
        pt = data.get("prompt_eval_count")
        ct = data.get("eval_count")
        if pt is not None or ct is not None:
            METER.record(pt, ct, estimated=False, role=self.role, model=self.model)
        else:
            METER.record(_est_tokens((system_prompt or "") + prompt),
                         _est_tokens(data.get("response", "")), estimated=True, role=self.role, model=self.model)
        return data["response"]

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        # httpx가 있으면 진짜 비동기, 없으면 thread 폴백
        if self._httpx is None:
            import asyncio
            return await asyncio.to_thread(self.generate, prompt, system_prompt)

        url = f"{self.host}/api/generate"
        options = {"temperature": self.temperature}
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt or "",
            "stream": False,
            "options": options,
        }

        async def _call():
            async with self._httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                pt = data.get("prompt_eval_count")
                ct = data.get("eval_count")
                if pt is not None or ct is not None:
                    METER.record(pt, ct, estimated=False, role=self.role, model=self.model)
                else:
                    METER.record(_est_tokens((system_prompt or "") + prompt),
                                 _est_tokens(data.get("response", "")), estimated=True, role=self.role, model=self.model)
                return data["response"]

        return await _call_with_async_retry(_call, max_retries=3, base_delay=2.0)



def _wrap_estimating(cls):
    """usage를 제공하지 않는 백엔드(Mock/Ollama)의 호출을 추정치로 계측기에 기록.
    estimated=True로 표시되므로 결과의 token_source가 'estimated'가 된다."""
    _orig_sync = cls.generate

    def generate(self, prompt, system_prompt=None):
        out = _orig_sync(self, prompt, system_prompt)
        METER.record(_est_tokens((system_prompt or "") + (prompt or "")),
                     _est_tokens(out), estimated=True, role=self.role, model=getattr(self, "model", "mock"))
        return out

    cls.generate = generate

    _orig_async = getattr(cls, "generate_async", None)
    if _orig_async is not None:
        async def generate_async(self, prompt, system_prompt=None):
            before = METER.snapshot()["calls"]
            out = await _orig_async(self, prompt, system_prompt)
            # Mock 의 generate_async 는 내부에서 (이미 감싸진) generate 를 부르므로 그때 기록됨.
            # 그 경우 다시 기록하면 호출·토큰이 2배로 잡힌다 (WEEK1 A2 이중 계수 버그).
            if METER.snapshot()["calls"] == before:
                METER.record(_est_tokens((system_prompt or "") + (prompt or "")),
                             _est_tokens(out), estimated=True, role=self.role, model=getattr(self, "model", "mock"))
            return out
        cls.generate_async = generate_async
    return cls


_wrap_estimating(MockLLMClient)
# OllamaClient는 prompt_eval_count/eval_count를 직접 기록하므로 래핑하지 않음


# ── 역할별 모델 지정 (WEEK1 A5) ──────────────────────────────────────────
# 역할명은 코드에 존재하는 것만: "builder"(build/self_revise 호출), "reviewer"(expert_review 호출).
# 환경변수 HARMONET_MODEL_DEFAULT / HARMONET_MODEL_BUILDER / HARMONET_MODEL_REVIEWER.
ROLES = ("builder", "reviewer")
_role_clients: Dict[str, "LLMClient"] = {}
_role_warned: set = set()


def _resolved_model(role: str) -> Optional[str]:
    """역할의 모델 설정 문자열. 역할별 → DEFAULT → None(백엔드 기본값)."""
    return os.getenv(f"HARMONET_MODEL_{role.upper()}") or os.getenv("HARMONET_MODEL_DEFAULT") or None


def _warn_once(key: str, msg: str) -> None:
    if key not in _role_warned:
        _role_warned.add(key)
        print(f"[LLM][WARN] {msg}")


def _assert_model_available(client: "LLMClient", role: str) -> None:
    """명시적으로 지정한 모델을 백엔드가 열 수 있는지 + 가격표에 있는지 확인. 어느 쪽이든 실패면 RuntimeError, 호출 0회
    (다른 모델로 대체하지 않는다). 가격 조회는 백엔드가 **보고할** id(models.retrieve 의 id, 날짜 접미사 정규화)로 한다 (Week2-B2)."""
    from harmonet.pricing import preflight_price
    model = getattr(client, "model", None)
    reported = model
    try:
        if type(client).__name__ == "ScenarioMockClient":
            preflight_price(model, role); return    # 시나리오 mock: 모델 이름의 가격표만 확인 (유료 호출 없음)
        if isinstance(client, OllamaClient):
            tags = client.requests.get(f"{client.host}/api/tags", timeout=5).json().get("models", [])
            if model not in {m["name"] for m in tags}:
                raise RuntimeError(f"Ollama 에 모델 {model!r} 이 없습니다 (ollama pull {model})")
        elif isinstance(client, (OpenAIClient, OpenAICompatibleClient, AnthropicClient)):
            info = client.client.models.retrieve(model)     # 무료 조회. 없으면 예외
            reported = getattr(info, "id", None) or model
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"[LLM] 역할 {role!r} 에 지정한 모델 {model!r} 을 백엔드가 열 수 없습니다: {exc}") from exc
    preflight_price(reported, role)                  # mock 은 prefix 규칙($0)으로 통과


def get_llm_client(role: Optional[str] = None) -> "LLMClient":
    """
    role 이 없으면 기본 클라이언트 싱글턴(기존 동작).
    role 이 있으면 그 역할 전용 클라이언트 (HARMONET_MODEL_<ROLE> 로 모델 지정, 없으면 DEFAULT, 없으면 백엔드 기본값+경고 1회).
    """
    if role is None:
        return _default_client()
    if role not in ROLES:
        raise ValueError(f"unknown LLM role {role!r}; expected one of {ROLES}")
    if role in _role_clients:
        return _role_clients[role]

    model = _resolved_model(role)
    if model is None:
        _warn_once(f"unset:{role}", f"역할 {role!r} 의 모델이 지정되지 않아 백엔드 기본 모델을 씁니다 "
                                     f"(HARMONET_MODEL_{role.upper()} 또는 HARMONET_MODEL_DEFAULT).")
    client = _build_client(model)
    client.role = role
    if model is not None:
        _assert_model_available(client, role)
    if role == "reviewer" and _resolved_model("builder") == _resolved_model("reviewer"):
        _warn_once("same:builder-reviewer", "builder 와 reviewer 가 같은 모델로 해석됩니다 — expert_review 와 self_revise 구별 불가.")
    _role_clients[role] = client
    return client


def _default_client() -> "LLMClient":
    global _llm_client_singleton
    if _llm_client_singleton is None:
        _llm_client_singleton = _build_client(None)
    return _llm_client_singleton


def _build_client(model: Optional[str]) -> "LLMClient":
    """
    HARMONET_LLM_BACKEND 에 따라 클라이언트 생성. model 이 있으면 그 모델로 (역할별 지정), 없으면 백엔드 기본값.

    선택 우선순위:
        1. HARMONET_LLM_BACKEND 환경변수가 명시되면 그것 사용
           (값: "openai" | "anthropic" | "ollama" | "runyourai" | "mock")
        2. OPENAI_API_KEY → OpenAIClient (gpt-4o-mini)
        3. ANTHROPIC_API_KEY → AnthropicClient (claude-sonnet-4-5)
        4. RUNYOURAI_API_KEY → RunYourAIClient
        5. OLLAMA_HOST 또는 localhost:11434 도달 가능 → OllamaClient (로컬)
        6. 그 외 → MockLLMClient

    로컬 AI 사용법:
        export HARMONET_LLM_BACKEND=ollama
        export OLLAMA_MODEL=llama3.1:8b          # 또는 qwen2.5:7b, mistral:7b
        export OLLAMA_HOST=http://localhost:11434  # (선택) 기본값
    """
    backend = os.getenv("HARMONET_LLM_BACKEND", "").lower().strip()

    # ── 1. 명시적 백엔드 지정 ────────────────────────────────────
    if backend == "openai":
        client = OpenAIClient(model=model)
        print(f"[LLM] OpenAI 클라이언트 활성화 ({client.model}) [HARMONET_LLM_BACKEND=openai]")
        return client
    if backend == "anthropic":
        client = AnthropicClient(model=model)
        print(f"[LLM] Anthropic 클라이언트 활성화 ({client.model}) [HARMONET_LLM_BACKEND=anthropic]")
        return client
    if backend == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        client = OllamaClient(host=host, model=model)
        print(f"[LLM] Ollama 로컬 클라이언트 활성화 ({model} @ {host}) [HARMONET_LLM_BACKEND=ollama]")
        return client
    if backend in ("openai_compatible", "compat", "ollama_openai"):
        base_url = os.getenv("OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1")
        model = model or os.getenv("OPENAI_COMPAT_MODEL", "qwen2.5:7b")
        client = OpenAICompatibleClient(
            api_key=os.getenv("OPENAI_COMPAT_API_KEY", "ollama"),
            base_url=base_url,
            model=model,
            temperature=float(os.getenv("OPENAI_COMPAT_TEMPERATURE", "0.2")),
            timeout=float(os.getenv("OPENAI_COMPAT_TIMEOUT_SECONDS", "300")),
            max_tokens=int(os.getenv("OPENAI_COMPAT_MAX_TOKENS", "1024")),
            label="OpenAI-Compatible",
        )
        print(f"[LLM] OpenAI 호환 클라이언트 활성화 ({model} @ {base_url}) "
              f"[HARMONET_LLM_BACKEND={backend}]")
        return client

    if backend in ("runyourai", "runyour"):
        client = RunYourAIClient(model=model)
        print(
            f"[LLM] RunYourAI 클라이언트 활성화 "
            f"({client.model} @ {client.base_url}) "
            f"[HARMONET_LLM_BACKEND=runyourai]"
        )
        return client
    if backend == "mock":
        client = MockLLMClient(model=model or "mock")
        print(f"[LLM] MockLLM 강제 활성화 ({client.model}) [HARMONET_LLM_BACKEND=mock]")
        return client
    if backend == "mock-scenario":                      # 유효 코드 mock (Week2-F1): 시나리오가 정한 변형 코드를 낸다, 유료 0
        from benchmark.mock_scenario import build_client
        client = build_client(model)
        print(f"[LLM] ScenarioMock 활성화 ({client.model}) [HARMONET_LLM_BACKEND=mock-scenario]")
        return client

    # ── 2. 자동 감지 (우선순위: OpenAI → Anthropic → RunYourAI → Ollama → Mock) ──
    # 키가 설정돼 있으면 그 백엔드를 쓰겠다는 뜻. 생성 실패를 삼키고 다음/Mock 으로 넘어가지 않는다 (WEEK1 A2).
    if os.getenv("OPENAI_API_KEY"):
        client = OpenAIClient(model=model)
        print(f"[LLM] OpenAI 클라이언트 활성화 ({client.model})")
        return client
    if os.getenv("ANTHROPIC_API_KEY"):
        client = AnthropicClient(model=model)
        print(f"[LLM] Anthropic 클라이언트 활성화 ({client.model}, 프롬프트 캐싱 ON)")
        return client
    if os.getenv("RUNYOURAI_API_KEY"):
        client = RunYourAIClient(model=model)
        print(f"[LLM] RunYourAI 클라이언트 자동 감지 ({client.model} @ {client.base_url})")
        return client

    # Ollama 자동 감지 — localhost:11434 도달 가능하면 사용
    try:
        import requests as _rq
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        r = _rq.get(f"{host}/api/tags", timeout=1.0)
        if r.ok:
            tags = [m["name"] for m in r.json().get("models", [])]
            model = model or os.getenv("OLLAMA_MODEL")
            if not model and tags:
                # 모델 자동 선택: 7B/8B 우선
                preferred = ("llama3.1:8b", "qwen2.5:7b", "mistral:7b", "llama3:8b", "phi3:mini")
                model = next((m for m in preferred if m in tags), tags[0])
            elif not model:
                model = "llama3.1:8b"
            client = OllamaClient(host=host, model=model)
            print(f"[LLM] Ollama 로컬 클라이언트 자동 감지 ({model} @ {host})")
            return client
    except Exception:
        pass  # Ollama 미기동은 '감지 실패'이지 오류가 아님 — 아래에서 명시적으로 중단한다

    # 어떤 백엔드도 설정되지 않았다. Mock 은 HARMONET_LLM_BACKEND=mock 으로만 켠다 (조용한 Mock 폴백 금지).
    raise RuntimeError(
        "[LLM] 사용할 백엔드가 없습니다. HARMONET_LLM_BACKEND 를 설정하세요 "
        "(mock | openai | anthropic | openai_compatible | ollama | runyourai) "
        "또는 OPENAI_API_KEY / ANTHROPIC_API_KEY / RUNYOURAI_API_KEY / Ollama 서버 중 하나를 준비하세요."
    )
