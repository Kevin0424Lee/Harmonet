"""G2 Track C operational readiness checks.

These tests cover the deployable service surface rather than benchmark quality:
health endpoints, Prometheus exposure, and container/orchestration manifests.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from harmonet.health import app


ROOT = Path(__file__).resolve().parents[1]


def test_healthz_is_fast_and_stable() -> None:
    client = TestClient(app)
    latencies: list[float] = []

    for _ in range(100):
        started = time.perf_counter()
        response = client.get("/healthz")
        latencies.append(time.perf_counter() - started)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert isinstance(payload["uptime_seconds"], (int, float))

    latencies.sort()
    p99 = latencies[int(len(latencies) * 0.99) - 1]
    assert p99 < 0.05


def test_readyz_ready_only_when_dependencies_or_explicit_allowance(monkeypatch) -> None:
    """WEEK1 A2: ready 는 하드코딩이 아니라 실제 의존성 — 임베딩 OK 이고 (Redis OK 또는 명시적으로 없이 운영)."""
    client = TestClient(app)
    monkeypatch.setenv("HARMONET_ALLOW_NO_REDIS", "1")
    response = client.get("/readyz")
    payload = response.json()
    assert set(payload["checks"]) == {"redis", "embedding", "faiss", "llm"}
    assert payload["checks"]["embedding"]["status"] == "ok", payload["checks"]["embedding"]
    assert payload["ready"] is True and response.status_code == 200


def test_readyz_not_ready_without_redis_unless_allowed(monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.delenv("HARMONET_ALLOW_NO_REDIS", raising=False)
    monkeypatch.delenv("HARMONET_DISABLE_REDIS", raising=False)
    monkeypatch.setenv("HARMONET_REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("HARMONET_REDIS_PORT", "1")  # 아무것도 안 듣는 포트
    response = client.get("/readyz")
    payload = response.json()
    assert payload["checks"]["redis"]["status"] == "unavailable"
    assert payload["ready"] is False and response.status_code == 503


def test_status_endpoint_exposes_service_metadata() -> None:
    client = TestClient(app)
    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "harmonet"
    assert "version" in payload
    assert "dependencies" in payload
    assert "config" in payload


def test_metrics_endpoint_exports_harmonet_prometheus_series() -> None:
    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    expected_series = [
        "harmonet_seeds_created_total",
        "harmonet_resonance_events_total",
        "harmonet_claim_latency_seconds",
        "harmonet_task_tokens_used",
        "harmonet_llm_requests_total",
    ]
    for series in expected_series:
        assert series in body


def test_dockerfile_defines_runtime_healthcheck_and_non_root_user() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim AS builder" in dockerfile
    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "USER harmonet" in dockerfile
    assert "EXPOSE 8080" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "http://localhost:8080/healthz" in dockerfile
    assert 'CMD ["python", "-m", "harmonet.health"' in dockerfile


def test_compose_declares_runtime_stack_and_service_healthcheck() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ["harmonet:", "redis:", "prometheus:", "grafana:"]:
        assert service in compose
    assert "target: runtime" in compose
    assert "8080:8080" in compose
    assert "6379:6379" in compose
    assert "9090:9090" in compose
    assert "3001:3000" in compose
    assert "condition: service_healthy" in compose
    assert "http://localhost:8080/healthz" in compose
    assert "harmonet-net" in compose


def test_prometheus_scrapes_harmonet_metrics_endpoint() -> None:
    prometheus = (ROOT / "deploy" / "prometheus.yml").read_text(encoding="utf-8")

    assert "job_name: harmonet" in prometheus
    assert 'targets: ["harmonet:8080"]' in prometheus
    assert "metrics_path: /metrics" in prometheus
    assert "scrape_interval: 10s" in prometheus


def test_grafana_datasource_points_to_prometheus() -> None:
    datasource = (
        ROOT
        / "deploy"
        / "grafana"
        / "provisioning"
        / "datasources"
        / "prometheus.yml"
    ).read_text(encoding="utf-8")

    assert "type: prometheus" in datasource
    assert "url: http://prometheus:9090" in datasource


def test_readyz_payload_is_json_serializable() -> None:
    client = TestClient(app)
    payload = client.get("/readyz").json()

    encoded = json.dumps(payload, ensure_ascii=False)
    assert '"ready": true' in encoded
