"""
harmonet/observability — 관측성 스택 (Logging · Metrics · Tracing)
===================================================================
사용 예시:
    from harmonet.observability import log, METRICS, get_tracer

    log.info("씨앗 투하", seed_id="abc", agent="Architect")
    METRICS.seeds_created.labels(agent="Architect", role="architect").inc()

    tracer = get_tracer()
    with tracer.start_as_current_span("scan_and_process"):
        ...
"""

from harmonet.observability.logging import get_logger, setup_logging, bind_request_id, bind_agent
from harmonet.observability.metrics import METRICS
from harmonet.observability.tracing import get_tracer, traced, set_span_attribute

# 기본 로거
log = get_logger("harmonet")

__all__ = [
    # Logging
    "log",
    "get_logger",
    "setup_logging",
    "bind_request_id",
    "bind_agent",
    # Metrics
    "METRICS",
    # Tracing
    "get_tracer",
    "traced",
    "set_span_attribute",
]
