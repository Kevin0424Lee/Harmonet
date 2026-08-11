"""
harmonet/observability/metrics.py — Prometheus 메트릭 정의
===========================================================
모든 카운터/히스토그램/게이지를 모듈 레벨 싱글턴으로 정의.

사용:
    from harmonet.observability.metrics import METRICS
    METRICS.seeds_created.labels(agent="Architect", role="architect").inc()
    with METRICS.claim_latency.labels(outcome="success").time():
        claim_seed(...)

HTTP 노출:
    GET /metrics → Prometheus scrape endpoint (harmonet/health.py)
"""

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    REGISTRY,
)


class HarmoNetMetrics:
    """HarmoNet 전체 메트릭 레지스트리."""

    def __init__(self, registry: CollectorRegistry = REGISTRY):
        self.registry = registry

        # ── 씨앗 관련 ─────────────────────────────────────────
        self.seeds_created = Counter(
            "harmonet_seeds_created_total",
            "씨앗 생성 횟수",
            ["agent", "role"],
            registry=registry,
        )
        self.seeds_deposited = Counter(
            "harmonet_seeds_deposited_total",
            "씨앗 투하 횟수 (필드에 실제 기록됨)",
            ["agent", "grid_position"],
            registry=registry,
        )
        self.seeds_expired = Counter(
            "harmonet_seeds_expired_total",
            "TTL 만료로 제거된 씨앗 수",
            registry=registry,
        )
        self.seed_registry_size = Gauge(
            "harmonet_seed_registry_size",
            "현재 씨앗 레지스트리 내 씨앗 수",
            registry=registry,
        )

        # ── 공명 관련 ─────────────────────────────────────────
        self.resonance_events = Counter(
            "harmonet_resonance_events_total",
            "공명 감지 이벤트 수",
            ["detector_agent", "seed_creator_agent"],
            registry=registry,
        )
        self.resonance_strength = Histogram(
            "harmonet_resonance_strength",
            "공명 강도 분포",
            buckets=[0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0],
            registry=registry,
        )
        self.resonance_delta = Gauge(
            "harmonet_resonance_delta",
            "현재 에이전트별 적응형 δ 임계값",
            ["agent"],
            registry=registry,
        )

        # ── 씨앗 선점 (Claim) ────────────────────────────────
        self.claim_attempts = Counter(
            "harmonet_claim_attempts_total",
            "씨앗 선점 시도 횟수",
            ["agent", "outcome"],  # outcome: success | already_claimed | expired
            registry=registry,
        )
        self.claim_latency = Histogram(
            "harmonet_claim_latency_seconds",
            "씨앗 선점 응답시간",
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
            labelnames=["outcome"],
            registry=registry,
        )

        # ── 작업 실행 ────────────────────────────────────────
        self.tasks_completed = Counter(
            "harmonet_tasks_completed_total",
            "에이전트 작업 완료 횟수",
            ["agent", "role", "success"],
            registry=registry,
        )
        self.task_execution_time = Histogram(
            "harmonet_task_execution_seconds",
            "작업 실행 시간",
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
            labelnames=["agent", "role"],
            registry=registry,
        )
        self.task_tokens_used = Histogram(
            "harmonet_task_tokens_used",
            "작업당 LLM 토큰 사용량",
            buckets=[10, 50, 100, 250, 500, 1000, 2000, 5000],
            labelnames=["agent"],
            registry=registry,
        )

        # ── SOC 관련 ─────────────────────────────────────────
        self.soc_cascades = Counter(
            "harmonet_soc_cascades_total",
            "SOC 캐스케이드(눈사태) 발생 횟수",
            registry=registry,
        )
        self.soc_cascade_size = Histogram(
            "harmonet_soc_cascade_size",
            "캐스케이드 크기 분포 (P(s) ~ s^(-α))",
            buckets=[1, 2, 3, 5, 8, 13, 21, 34],
            registry=registry,
        )
        self.soc_activation_level = Gauge(
            "harmonet_soc_activation_level",
            "에이전트 SOC 활성화 레벨",
            ["agent"],
            registry=registry,
        )

        # ── Kuramoto 동기화 ───────────────────────────────────
        self.kuramoto_r = Gauge(
            "harmonet_kuramoto_r",
            "쿠라모토 질서 파라미터 r ∈ [0, 1]",
            registry=registry,
        )
        self.kuramoto_psi = Gauge(
            "harmonet_kuramoto_psi_radians",
            "쿠라모토 평균 위상 ψ (라디안)",
            registry=registry,
        )

        # ── 필드 에너지 ──────────────────────────────────────
        self.field_energy = Gauge(
            "harmonet_field_energy",
            "데이터 우주 전체 에너지 합",
            registry=registry,
        )
        self.field_propagations = Counter(
            "harmonet_field_propagations_total",
            "필드 확산(propagate) 호출 횟수",
            registry=registry,
        )

        # ── Redis 스토어 ──────────────────────────────────────
        self.redis_operations = Counter(
            "harmonet_redis_operations_total",
            "Redis 연산 횟수",
            ["operation", "outcome"],  # outcome: success | fallback
            registry=registry,
        )
        self.redis_sync_latency = Histogram(
            "harmonet_redis_sync_latency_seconds",
            "Redis 씨앗 동기화 왕복 시간",
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.5],
            registry=registry,
        )

        # ── LLM API ───────────────────────────────────────────
        self.llm_requests = Counter(
            "harmonet_llm_requests_total",
            "LLM API 호출 횟수",
            ["backend", "outcome"],  # outcome: success | retry | error
            registry=registry,
        )
        self.llm_latency = Histogram(
            "harmonet_llm_latency_seconds",
            "LLM API 응답 시간",
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
            labelnames=["backend"],
            registry=registry,
        )
        self.llm_tokens = Counter(
            "harmonet_llm_tokens_total",
            "LLM 토큰 사용량",
            ["backend", "token_type"],  # token_type: prompt | completion
            registry=registry,
        )


# ── 전역 싱글턴 ───────────────────────────────────────────────────
METRICS = HarmoNetMetrics()
