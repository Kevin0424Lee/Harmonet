"""
harmonet/health.py — FastAPI 헬스체크 & 메트릭 서버
======================================================
엔드포인트:
    GET /healthz  → 라이브니스 프로브 (항상 200 OK)
    GET /readyz   → 레디니스 프로브 (Redis 연결, 의존성 체크)
    GET /metrics  → Prometheus scrape endpoint
    GET /status   → JSON 상태 (버전, 에이전트 수, 필드 에너지 등)

실행:
    python -m harmonet.health                        # 기본 8080 포트
    python -m harmonet.health --port 9090

테스트:
    curl http://localhost:8080/healthz
    curl http://localhost:8080/readyz
    curl http://localhost:8080/metrics
"""

import os
import sys
import time
import argparse
import socket
from typing import Any, Dict

from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse
import uvicorn
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

# ── 메트릭 사전 등록 (중요!) ──────────────────────────────────────
# METRICS 싱글턴을 임포트해야 /metrics 엔드포인트에 HarmoNet 메트릭이 노출됨.
# 이 임포트가 없으면 Prometheus 기본 메트릭(python_*)만 보임.
from harmonet.observability import METRICS as _METRICS  # noqa: F401
from harmonet.observability import log

# ── 앱 초기화 ─────────────────────────────────────────────────────

app = FastAPI(
    title="HarmoNet Health & Metrics",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

_START_TIME = time.time()


# ── 의존성 체크 ───────────────────────────────────────────────────

def _check_redis() -> Dict[str, Any]:
    """Redis 연결 확인. store 와 같은 접속 정보를 쓴다 (예전엔 REDIS_HOST 만 봐서 store 와 어긋났음)."""
    from .store import redis_endpoint
    try:
        host, port = redis_endpoint()
        with socket.create_connection((host, port), timeout=0.2) as conn:
            conn.settimeout(0.2)
            conn.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = conn.recv(16)
        if response.startswith(b"+PONG"):
            return {"status": "ok", "host": host, "port": port}
        return {"status": "unavailable", "host": host, "port": port, "note": "unexpected Redis ping response"}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc), "note": "fallback 모드"}


def _check_faiss() -> Dict[str, Any]:
    """FAISS 인덱스 가용 여부 확인."""
    try:
        import faiss  # noqa
        return {"status": "ok"}
    except ImportError:
        return {"status": "unavailable", "note": "brute-force 폴백 사용"}


def _check_llm() -> Dict[str, Any]:
    """설정된 LLM 백엔드 보고 (키 유무로 추측하지 않는다)."""
    backend = os.environ.get("HARMONET_LLM_BACKEND", "").lower() or "(unset → get_llm_client 자동 감지)"
    return {"status": "mock" if backend == "mock" else "configured", "backend": backend}


def _check_embedding() -> Dict[str, Any]:
    """임베딩 모델이 실제로 로드되는지 (난수 폴백이면 실패)."""
    try:
        from .embed import assert_embedding_sane
        gap = assert_embedding_sane()
        return {"status": "ok", "cos_gap": round(gap, 3)}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)[:200]}


# ── 엔드포인트 ────────────────────────────────────────────────────

@app.get("/healthz", summary="라이브니스 프로브")
async def liveness():
    """
    Kubernetes liveness probe.
    프로세스가 살아있으면 항상 200 OK.
    """
    return {"status": "ok", "uptime_seconds": round(time.time() - _START_TIME, 1)}


@app.get("/readyz", summary="레디니스 프로브")
async def readiness():
    """
    Kubernetes readiness probe.
    ready 조건 (하드코딩 True 였던 것을 실제 의존성으로 교체 — WEEK1 A2):
      - 임베딩 모델이 로드되고 건전성 검사를 통과
      - Redis 에 연결되거나, HARMONET_ALLOW_NO_REDIS=1 / HARMONET_DISABLE_REDIS=1 로 명시적으로 없이 운영
    """
    checks = {
        "redis": _check_redis(),
        "embedding": _check_embedding(),
        "faiss": _check_faiss(),
        "llm": _check_llm(),
    }
    redis_optional = os.environ.get("HARMONET_ALLOW_NO_REDIS") == "1" or \
        os.environ.get("HARMONET_DISABLE_REDIS", "").lower() in {"1", "true", "yes"}
    ready = checks["embedding"]["status"] == "ok" and (checks["redis"]["status"] == "ok" or redis_optional)

    return Response(
        content=__import__("json").dumps({
            "ready": ready,
            "checks": checks,
            "uptime_seconds": round(time.time() - _START_TIME, 1),
        }),
        status_code=200 if ready else 503,
        media_type="application/json",
    )


@app.get("/metrics", summary="Prometheus 메트릭 scrape", response_class=PlainTextResponse)
async def metrics():
    """Prometheus 형식 메트릭 출력."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/status", summary="상세 상태 JSON")
async def status():
    """HarmoNet 런타임 상태 (모니터링 대시보드용)."""
    import platform

    return {
        "service": "harmonet",
        "version": _get_version(),
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "python": platform.python_version(),
        "platform": platform.system(),
        "dependencies": {
            "redis": _check_redis(),
            "faiss": _check_faiss(),
            "llm": _check_llm(),
        },
        "config": {
            "log_level": os.environ.get("HARMONET_LOG_LEVEL", "INFO"),
            "tracing": os.environ.get("HARMONET_TRACING", "false"),
            "redis_host": os.environ.get("REDIS_HOST", "localhost"),
        },
    }


def _get_version() -> str:
    try:
        from harmonet import __version__
        return __version__
    except Exception:
        return "dev"


# ── CLI 진입점 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HarmoNet 헬스/메트릭 서버")
    parser.add_argument("--host", default="0.0.0.0", help="바인드 호스트")
    parser.add_argument("--port", type=int, default=8080, help="포트 (기본: 8080)")
    parser.add_argument("--reload", action="store_true", help="개발 자동 리로드")
    args = parser.parse_args()

    print(f"[Health] 서버 시작: http://{args.host}:{args.port}")
    print(f"  /healthz  — 라이브니스")
    print(f"  /readyz   — 레디니스")
    print(f"  /metrics  — Prometheus")
    print(f"  /status   — 상세 상태")

    uvicorn.run(
        "harmonet.health:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
