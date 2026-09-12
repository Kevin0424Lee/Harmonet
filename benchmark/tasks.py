"""
benchmark/tasks.py — 표준화된 벤치마크 태스크 정의
====================================================
20개 태스크 × 4개 카테고리 (코드 생성, API 설계, 디버깅, 리팩토링).

각 태스크는 다음을 포함:
- id: 고유 식별자
- category: 태스크 유형
- prompt: 에이전트에게 전달할 지시문
- expected_keywords: 성공 판단용 키워드 목록 (출력에 하나 이상 포함 시 성공)
- complexity: 1(간단) ~ 3(복잡)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BenchmarkTask:
    id: str
    category: str
    prompt: str
    expected_keywords: List[str]
    complexity: int  # 1, 2, 3
    # 기계 검증용 명세 (harmonet/verify.py task_spec 형식). 러너가 채움; 없으면 validator는 AST 검사만.
    spec: Optional[Dict[str, Any]] = None


# ── 카테고리 1: 코드 생성 (Code Generation) ──────────────────────
CODE_GEN_TASKS = [
    BenchmarkTask(
        id="cg_01",
        category="code_gen",
        prompt=(
            "Write a Python function `validate_jwt(token: str, secret: str) -> dict` "
            "that validates a JWT token using HMAC-SHA256, raises ValueError on failure, "
            "and returns the decoded payload."
        ),
        expected_keywords=["jwt", "hmac", "sha256", "decode", "ValueError", "payload"],
        complexity=2,
    ),
    BenchmarkTask(
        id="cg_02",
        category="code_gen",
        prompt=(
            "Implement a Python async context manager `RedisLock(key, timeout)` "
            "that acquires a distributed lock via Redis SETNX and releases it on exit."
        ),
        expected_keywords=["setnx", "async", "contextmanager", "acquire", "release", "redis"],
        complexity=2,
    ),
    BenchmarkTask(
        id="cg_03",
        category="code_gen",
        prompt=(
            "Write a Python decorator `@retry(max_attempts=3, backoff=2.0)` "
            "that retries the wrapped function with exponential backoff on exception."
        ),
        expected_keywords=["retry", "backoff", "sleep", "attempts", "exception", "decorator"],
        complexity=2,
    ),
    BenchmarkTask(
        id="cg_04",
        category="code_gen",
        prompt=(
            "Create a FastAPI route `POST /users/` that accepts a Pydantic `UserCreate` model, "
            "hashes the password with bcrypt, saves to SQLAlchemy DB, and returns `UserOut`."
        ),
        expected_keywords=["fastapi", "pydantic", "bcrypt", "sqlalchemy", "POST", "hash"],
        complexity=3,
    ),
    BenchmarkTask(
        id="cg_05",
        category="code_gen",
        prompt=(
            "Implement a Python LRU cache class `LRUCache(capacity: int)` with O(1) "
            "`get(key)` and `put(key, value)` methods using OrderedDict."
        ),
        expected_keywords=["LRU", "OrderedDict", "get", "put", "capacity", "O(1)"],
        complexity=2,
    ),
]

# ── 카테고리 2: API 설계 (API Design) ────────────────────────────
API_DESIGN_TASKS = [
    BenchmarkTask(
        id="api_01",
        category="api_design",
        prompt=(
            "Design a RESTful API for a multi-tenant SaaS authentication service. "
            "Include endpoints for signup, login, token refresh, logout, and password reset. "
            "Specify HTTP methods, paths, request/response schemas, and error codes."
        ),
        expected_keywords=["POST", "refresh", "logout", "401", "tenant", "schema"],
        complexity=3,
    ),
    BenchmarkTask(
        id="api_02",
        category="api_design",
        prompt=(
            "Design an OpenAPI 3.0 schema for a webhook notification system. "
            "Include endpoints to register webhooks, list them, update, delete, "
            "and resend failed deliveries. Include authentication via Bearer token."
        ),
        expected_keywords=["openapi", "webhook", "Bearer", "resend", "DELETE", "schema"],
        complexity=3,
    ),
    BenchmarkTask(
        id="api_03",
        category="api_design",
        prompt=(
            "Design a GraphQL schema for a blog system with Users, Posts, Comments, and Tags. "
            "Include queries for feed, search, and mutations for CRUD operations."
        ),
        expected_keywords=["graphql", "query", "mutation", "User", "Post", "Comment"],
        complexity=2,
    ),
    BenchmarkTask(
        id="api_04",
        category="api_design",
        prompt=(
            "Design a gRPC service definition (.proto) for a real-time collaborative "
            "document editing system supporting operational transforms."
        ),
        expected_keywords=["proto", "service", "rpc", "stream", "message", "operation"],
        complexity=3,
    ),
    BenchmarkTask(
        id="api_05",
        category="api_design",
        prompt=(
            "Design a rate limiting strategy for a public API. "
            "Describe the algorithm (token bucket vs sliding window), "
            "Redis data structures used, and HTTP response headers."
        ),
        expected_keywords=["rate", "limit", "token bucket", "redis", "X-RateLimit", "429"],
        complexity=2,
    ),
]

# ── 카테고리 3: 디버깅 (Debugging) ───────────────────────────────
DEBUG_TASKS = [
    BenchmarkTask(
        id="dbg_01",
        category="debugging",
        prompt=(
            "Debug this Python code. It should return a list of prime numbers up to n, "
            "but always returns an empty list:\n\n"
            "```python\n"
            "def primes_up_to(n):\n"
            "    result = []\n"
            "    for i in range(2, n):\n"
            "        for j in range(2, i):\n"
            "            if i % j == 0:\n"
            "                result.append(i)\n"
            "                break\n"
            "    return result\n"
            "```\n"
            "Explain the bug and provide the fixed version."
        ),
        expected_keywords=["break", "append", "prime", "fix", "not prime", "composite"],
        complexity=1,
    ),
    BenchmarkTask(
        id="dbg_02",
        category="debugging",
        prompt=(
            "This async Python function causes a deadlock. Identify the cause and fix it:\n\n"
            "```python\n"
            "import asyncio\n"
            "lock = asyncio.Lock()\n\n"
            "async def task_a():\n"
            "    async with lock:\n"
            "        await task_b()\n\n"
            "async def task_b():\n"
            "    async with lock:\n"
            "        print('done')\n"
            "```"
        ),
        expected_keywords=["deadlock", "reentrant", "lock", "acquired", "nested", "fix"],
        complexity=2,
    ),
    BenchmarkTask(
        id="dbg_03",
        category="debugging",
        prompt=(
            "This SQLAlchemy query causes N+1 problem. Identify it and optimize:\n\n"
            "```python\n"
            "users = session.query(User).all()\n"
            "for user in users:\n"
            "    print(user.posts)  # triggers SELECT per user\n"
            "```"
        ),
        expected_keywords=["N+1", "joinedload", "eager", "lazy", "query", "optimize"],
        complexity=2,
    ),
    BenchmarkTask(
        id="dbg_04",
        category="debugging",
        prompt=(
            "A FastAPI endpoint returns 422 Unprocessable Entity for valid requests. "
            "The Pydantic model uses `datetime` but clients send Unix timestamps. "
            "How do you fix this without changing the client?"
        ),
        expected_keywords=["validator", "pydantic", "datetime", "timestamp", "422", "field_validator"],
        complexity=2,
    ),
    BenchmarkTask(
        id="dbg_05",
        category="debugging",
        prompt=(
            "A Python application has a memory leak. The heap grows by ~50MB/hour. "
            "The codebase uses a global dict `_cache = {}` populated in a request handler. "
            "Diagnose and provide three different solutions."
        ),
        expected_keywords=["memory", "leak", "cache", "evict", "LRU", "TTL", "maxsize"],
        complexity=2,
    ),
]

# ── 카테고리 4: 리팩토링 (Refactoring) ───────────────────────────
REFACTOR_TASKS = [
    BenchmarkTask(
        id="ref_01",
        category="refactoring",
        prompt=(
            "Refactor this God class into SOLID-compliant components. "
            "It currently handles authentication, email sending, database writes, "
            "and audit logging all in one 800-line class. "
            "Propose the decomposed class structure with interfaces."
        ),
        expected_keywords=["single responsibility", "interface", "dependency injection",
                           "service", "repository", "SOLID"],
        complexity=3,
    ),
    BenchmarkTask(
        id="ref_02",
        category="refactoring",
        prompt=(
            "Convert this callback-based async code to async/await pattern:\n\n"
            "```python\n"
            "def fetch_user(user_id, callback):\n"
            "    db.find(user_id, on_success=callback, on_error=lambda e: log(e))\n"
            "```\n"
            "Show the promisified version using asyncio."
        ),
        expected_keywords=["async", "await", "asyncio", "Future", "callback", "coroutine"],
        complexity=2,
    ),
    BenchmarkTask(
        id="ref_03",
        category="refactoring",
        prompt=(
            "Refactor deeply nested conditional logic (5+ levels of if/else) "
            "in a payment processing function using guard clauses and early returns. "
            "Show before and after."
        ),
        expected_keywords=["guard clause", "early return", "flatten", "nested", "refactor"],
        complexity=2,
    ),
    BenchmarkTask(
        id="ref_04",
        category="refactoring",
        prompt=(
            "Migrate this synchronous Django ORM code to async using "
            "Django 4.1+ async ORM. Handle transaction management and "
            "connection pooling considerations."
        ),
        expected_keywords=["async", "aget", "afilter", "transaction", "sync_to_async", "await"],
        complexity=2,
    ),
    BenchmarkTask(
        id="ref_05",
        category="refactoring",
        prompt=(
            "Refactor a monolithic 2000-line Flask app into a "
            "microservices architecture. Identify service boundaries, "
            "define inter-service communication (REST vs message queue), "
            "and describe the data decomposition strategy."
        ),
        expected_keywords=["microservice", "boundary", "message queue", "data", "decomposition", "service"],
        complexity=3,
    ),
]

# ── 전체 태스크 집합 ───────────────────────────────────────────────
ALL_TASKS: List[BenchmarkTask] = (
    CODE_GEN_TASKS + API_DESIGN_TASKS + DEBUG_TASKS + REFACTOR_TASKS
)

TASKS_BY_CATEGORY = {
    "code_gen":    CODE_GEN_TASKS,
    "api_design":  API_DESIGN_TASKS,
    "debugging":   DEBUG_TASKS,
    "refactoring": REFACTOR_TASKS,
}


def get_tasks(
    categories: List[str] | None = None,
    max_complexity: int = 3,
    limit: int | None = None,
) -> List[BenchmarkTask]:
    """필터링된 태스크 목록 반환."""
    tasks = ALL_TASKS
    if categories:
        tasks = [t for t in tasks if t.category in categories]
    tasks = [t for t in tasks if t.complexity <= max_complexity]
    if limit:
        tasks = tasks[:limit]
    return tasks
