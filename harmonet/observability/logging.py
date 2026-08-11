"""
harmonet/observability/logging.py — 구조화 로깅 (structlog)
=============================================================
correlation_id 자동 주입, JSON 출력 (프로덕션), 컬러 콘솔 (개발).

사용:
    from harmonet.observability.logging import get_logger, bind_request_id
    log = get_logger(__name__)

    with bind_request_id("req-abc123"):
        log.info("씨앗 투하", seed_id="abc", agent="Architect")
"""

import logging
import os
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Generator

import structlog

# ── Correlation ID context variable ───────────────────────────────
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_agent_id: ContextVar[str] = ContextVar("agent_id", default="")


def get_correlation_id() -> str:
    return _correlation_id.get() or "no-corr-id"


@contextmanager
def bind_request_id(request_id: str | None = None) -> Generator[str, None, None]:
    """요청 범위 내에 correlation_id를 바인딩."""
    rid = request_id or str(uuid.uuid4())[:8]
    token = _correlation_id.set(rid)
    try:
        yield rid
    finally:
        _correlation_id.reset(token)


@contextmanager
def bind_agent(agent_id: str) -> Generator[None, None, None]:
    """에이전트 컨텍스트 바인딩."""
    token = _agent_id.set(agent_id)
    try:
        yield
    finally:
        _agent_id.reset(token)


# ── 공통 프로세서: correlation_id + agent_id 자동 주입 ───────────

def _inject_context(logger: Any, method: str, event_dict: Dict) -> Dict:
    corr = _correlation_id.get()
    if corr:
        event_dict["correlation_id"] = corr
    aid = _agent_id.get()
    if aid:
        event_dict["agent_id"] = aid
    return event_dict


# ── 환경별 설정 ───────────────────────────────────────────────────

def setup_logging(
    level: str = "INFO",
    json_output: bool | None = None,
) -> None:
    """
    structlog 전역 설정.

    Args:
        level: 로그 레벨 ("DEBUG", "INFO", "WARNING", "ERROR")
        json_output: True=JSON, False=컬러 콘솔, None=환경 자동 감지
    """
    if json_output is None:
        # HARMONET_LOG_FORMAT=json 으로 강제 가능
        json_output = os.environ.get("HARMONET_LOG_FORMAT", "").lower() == "json"

    log_level = getattr(logging, level.upper(), logging.INFO)

    # stdlib logging 기본 설정
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_context,
    ]

    if json_output:
        # 프로덕션: JSON Lines 출력
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # 개발: 컬러 콘솔
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "harmonet") -> structlog.stdlib.BoundLogger:
    """모듈별 로거 반환."""
    return structlog.get_logger(name)


# ── 기본 초기화 (임포트 시 자동) ─────────────────────────────────
_level = os.environ.get("HARMONET_LOG_LEVEL", "INFO")
setup_logging(level=_level)
