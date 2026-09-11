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
from typing import Optional

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
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass

    @abstractmethod
    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass



class MockLLMClient(LLMClient):
    """API 키가 없을 때 작동하는 하이브리드 Mock LLM"""
    
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

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is missing.")
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
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
        )
        METER.record_from_response(response)
        return response.choices[0].message.content

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """AsyncOpenAI로 이벤트 루프 블로킹 없이 진짜 비동기 처리 (지수 백오프 재시도)"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async def _call():
            return await self.async_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.2,
            )

        response = await _call_with_async_retry(_call)
        METER.record_from_response(response)
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
        METER.record_from_response(response)
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
        METER.record_from_response(response)
        return response.choices[0].message.content or ""


class RunYourAIClient(OpenAICompatibleClient):
    """RunYourAI API router client using its OpenAI-compatible endpoint."""

    def __init__(self, api_key: Optional[str] = None):
        max_tokens = os.getenv("RUNYOURAI_MAX_TOKENS")
        super().__init__(
            api_key=api_key or os.getenv("RUNYOURAI_API_KEY"),
            base_url=os.getenv("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1"),
            model=os.getenv("RUNYOURAI_MODEL", "runyour/free"),
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

    @_retry_sync(max_retries=3, base_delay=2.0)
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        response = self.client.messages.create(**self._msg_kwargs(prompt, self._build_system_blocks(system_prompt)))
        METER.record_from_response(response)
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
        METER.record_from_response(response)
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
            METER.record(pt, ct, estimated=False)
        else:
            METER.record(_est_tokens((system_prompt or "") + prompt),
                         _est_tokens(data.get("response", "")), estimated=True)
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
                    METER.record(pt, ct, estimated=False)
                else:
                    METER.record(_est_tokens((system_prompt or "") + prompt),
                                 _est_tokens(data.get("response", "")), estimated=True)
                return data["response"]

        return await _call_with_async_retry(_call, max_retries=3, base_delay=2.0)



def _wrap_estimating(cls):
    """usage를 제공하지 않는 백엔드(Mock/Ollama)의 호출을 추정치로 계측기에 기록.
    estimated=True로 표시되므로 결과의 token_source가 'estimated'가 된다."""
    _orig_sync = cls.generate

    def generate(self, prompt, system_prompt=None):
        out = _orig_sync(self, prompt, system_prompt)
        METER.record(_est_tokens((system_prompt or "") + (prompt or "")),
                     _est_tokens(out), estimated=True)
        return out

    cls.generate = generate

    _orig_async = getattr(cls, "generate_async", None)
    if _orig_async is not None:
        async def generate_async(self, prompt, system_prompt=None):
            out = await _orig_async(self, prompt, system_prompt)
            METER.record(_est_tokens((system_prompt or "") + (prompt or "")),
                         _est_tokens(out), estimated=True)
            return out
        cls.generate_async = generate_async
    return cls


_wrap_estimating(MockLLMClient)
# OllamaClient는 prompt_eval_count/eval_count를 직접 기록하므로 래핑하지 않음


def get_llm_client() -> LLMClient:
    """
    LLM 클라이언트 싱글턴 반환.

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
    global _llm_client_singleton
    if _llm_client_singleton is not None:
        return _llm_client_singleton

    backend = os.getenv("HARMONET_LLM_BACKEND", "").lower().strip()

    # ── 1. 명시적 백엔드 지정 ────────────────────────────────────
    if backend == "openai":
        _llm_client_singleton = OpenAIClient()
        print(f"[LLM] OpenAI 클라이언트 활성화 (gpt-4o-mini) [HARMONET_LLM_BACKEND=openai]")
        return _llm_client_singleton
    if backend == "anthropic":
        _llm_client_singleton = AnthropicClient()
        print(f"[LLM] Anthropic 클라이언트 활성화 ({_llm_client_singleton.model}) [HARMONET_LLM_BACKEND=anthropic]")
        return _llm_client_singleton
    if backend == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        _llm_client_singleton = OllamaClient(host=host, model=model)
        print(f"[LLM] Ollama 로컬 클라이언트 활성화 ({model} @ {host}) [HARMONET_LLM_BACKEND=ollama]")
        return _llm_client_singleton
    if backend in ("openai_compatible", "compat", "ollama_openai"):
        base_url = os.getenv("OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1")
        model = os.getenv("OPENAI_COMPAT_MODEL", "qwen2.5:7b")
        _llm_client_singleton = OpenAICompatibleClient(
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
        return _llm_client_singleton

    if backend in ("runyourai", "runyour"):
        _llm_client_singleton = RunYourAIClient()
        print(
            f"[LLM] RunYourAI 클라이언트 활성화 "
            f"({_llm_client_singleton.model} @ {_llm_client_singleton.base_url}) "
            f"[HARMONET_LLM_BACKEND=runyourai]"
        )
        return _llm_client_singleton
    if backend == "mock":
        _llm_client_singleton = MockLLMClient()
        print("[LLM] MockLLM 강제 활성화 [HARMONET_LLM_BACKEND=mock]")
        return _llm_client_singleton

    # ── 2. 자동 감지 (우선순위: OpenAI → Anthropic → RunYourAI → Ollama → Mock) ──
    if os.getenv("OPENAI_API_KEY"):
        try:
            _llm_client_singleton = OpenAIClient()
            print("[LLM] OpenAI 클라이언트 활성화 (gpt-4o-mini)")
            return _llm_client_singleton
        except Exception:
            pass
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            _llm_client_singleton = AnthropicClient()
            print(f"[LLM] Anthropic 클라이언트 활성화 ({_llm_client_singleton.model}, 프롬프트 캐싱 ON)")
            return _llm_client_singleton
        except Exception:
            pass
    if os.getenv("RUNYOURAI_API_KEY"):
        try:
            _llm_client_singleton = RunYourAIClient()
            print(
                f"[LLM] RunYourAI 클라이언트 자동 감지 "
                f"({_llm_client_singleton.model} @ {_llm_client_singleton.base_url})"
            )
            return _llm_client_singleton
        except Exception:
            pass

    # Ollama 자동 감지 — localhost:11434 도달 가능하면 사용
    try:
        import requests as _rq
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        r = _rq.get(f"{host}/api/tags", timeout=1.0)
        if r.ok:
            tags = [m["name"] for m in r.json().get("models", [])]
            model = os.getenv("OLLAMA_MODEL")
            if not model and tags:
                # 모델 자동 선택: 7B/8B 우선
                preferred = ("llama3.1:8b", "qwen2.5:7b", "mistral:7b", "llama3:8b", "phi3:mini")
                model = next((m for m in preferred if m in tags), tags[0])
            elif not model:
                model = "llama3.1:8b"
            _llm_client_singleton = OllamaClient(host=host, model=model)
            print(f"[LLM] Ollama 로컬 클라이언트 자동 감지 ({model} @ {host})")
            return _llm_client_singleton
    except Exception:
        pass

    _llm_client_singleton = MockLLMClient()
    print("[LLM] MockLLM 활성화 (실제 LLM 사용 옵션: "
          "OPENAI_API_KEY, ANTHROPIC_API_KEY, RUNYOURAI_API_KEY, 또는 Ollama 로컬 서버)")
    return _llm_client_singleton
