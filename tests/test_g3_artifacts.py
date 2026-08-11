from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_g3_runner_exists_and_has_required_modes() -> None:
    runner = (ROOT / "benchmark" / "g3_runner.py").read_text(encoding="utf-8")
    for expected in [
        "def reliability(",
        "def load_test(",
        "def failure_recovery(",
        "def security_scan(",
        "def cost_analysis(",
        "def run_all(",
    ]:
        assert expected in runner


def test_prod_requirements_do_not_include_benchmark_frameworks() -> None:
    prod = (ROOT / "requirements-prod.txt").read_text(encoding="utf-8")
    blocked = ["langgraph", "langchain", "sentence-transformers", "torch", "transformers"]
    for package in blocked:
        assert package not in prod


def test_dockerfile_prefers_prod_requirements_when_present() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements-prod.txt" in dockerfile
    assert "pip install --no-cache-dir --prefix=/install -r requirements-prod.txt" in dockerfile


def test_prometheus_alert_rules_are_mounted_and_configured() -> None:
    prometheus = (ROOT / "deploy" / "prometheus.yml").read_text(encoding="utf-8")
    alerts = (ROOT / "deploy" / "prometheus-alerts.yml").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "rule_files:" in prometheus
    assert "/etc/prometheus/prometheus-alerts.yml" in prometheus
    assert "./deploy/prometheus-alerts.yml:/etc/prometheus/prometheus-alerts.yml:ro" in compose
    for alert in ["HarmoNetHealthDown", "HarmoNetLLMErrorSpike", "HarmoNetTokenSpike", "HarmoNetRedisFallback"]:
        assert alert in alerts


def test_g3_runbook_exists() -> None:
    runbook = ROOT / "output" / "g3" / "HarmoNet_G3_Operations_Runbook_20260603.md"
    text = runbook.read_text(encoding="utf-8")
    assert "24-hour reliability run" in text.lower()
    assert "G3 Pass Criteria" in text
