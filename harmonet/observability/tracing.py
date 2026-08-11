"""
harmonet/observability/tracing.py — OpenTelemetry 분산 추적
=============================================================
스팬 계층:
    scan_and_process
      └─ claim_seed
      └─ llm_generate
      └─ deposit_feedback_seed

OTLP exporter (Jaeger / Tempo 등)로 전송.
환경변수:
    OTEL_EXPORTER_OTLP_ENDPOINT  기본: http://localhost:4317
    OTEL_SERVICE_NAME            기본: harmonet
    HARMONET_TRACING             "true" 일 때만 활성화

사용:
    from harmonet.observability.tracing import get_tracer, traced
    tracer = get_tracer()

    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("agent.id", "Architect")
        ...

    @traced("my_func")
    def my_func(...):
        ...
"""

import os
import functools
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_TRACING_ENABLED = os.environ.get("HARMONET_TRACING", "false").lower() == "true"
_tracer = None


def _setup_tracer():
    """OTel tracer 초기화 (최초 1회)."""
    global _tracer
    if _tracer is not None:
        return _tracer

    if not _TRACING_ENABLED:
        # No-op tracer
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("harmonet.noop")
        return _tracer

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME

        service_name = os.environ.get("OTEL_SERVICE_NAME", "harmonet")
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

        resource = Resource.create({SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("harmonet", schema_url="https://harmonet.ai/schema")

        print(f"[Tracing] OTel 활성화 → {endpoint} (service={service_name})")
        return _tracer

    except Exception as exc:
        print(f"[Tracing] OTel 초기화 실패 ({exc}), no-op으로 폴백")
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("harmonet.noop")
        return _tracer


def get_tracer():
    """현재 활성화된 OTel tracer 반환."""
    return _setup_tracer()


def traced(span_name: str | None = None, **fixed_attrs):
    """
    함수/메서드에 OTel 스팬을 자동으로 붙이는 데코레이터.

    예시:
        @traced("claim_seed", component="field")
        def claim_seed(self, seed_id, agent_id):
            ...
    """
    def decorator(func: F) -> F:
        name = span_name or func.__qualname__

        if asyncio_available and asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                tracer = get_tracer()
                with tracer.start_as_current_span(name) as span:
                    for k, v in fixed_attrs.items():
                        span.set_attribute(k, str(v))
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(StatusCode.ERROR, str(exc))
                        raise
            return async_wrapper  # type: ignore
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                tracer = get_tracer()
                with tracer.start_as_current_span(name) as span:
                    for k, v in fixed_attrs.items():
                        span.set_attribute(k, str(v))
                    try:
                        return func(*args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(StatusCode.ERROR, str(exc))
                        raise
            return sync_wrapper  # type: ignore

    return decorator


# OTel status 코드 (임포트 실패 시 폴백)
try:
    from opentelemetry.trace import StatusCode
    import asyncio
    asyncio_available = True
except ImportError:
    class StatusCode:  # type: ignore
        ERROR = "ERROR"
    asyncio_available = False

try:
    import asyncio
    asyncio_available = True
except ImportError:
    asyncio_available = False


# ── 편의 함수: 현재 스팬에 속성 추가 ─────────────────────────────

def set_span_attribute(key: str, value: Any) -> None:
    """현재 활성 스팬에 속성 추가 (없으면 no-op)."""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(key, str(value))
    except Exception:
        pass
