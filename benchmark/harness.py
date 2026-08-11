"""
benchmark/harness.py — 공정 측정 하네스
=========================================
동일한 태스크를 여러 에이전트 시스템에서 실행하고
토큰 비용·성공률·지연시간을 측정합니다.

사용법:
    from benchmark.harness import BenchmarkHarness, SystemAdapter
    harness = BenchmarkHarness()
    result = harness.run_task(adapter, task)
"""

import time
import json
import re
import statistics
import math
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Protocol
from pathlib import Path

from .tasks import BenchmarkTask


# ── 측정 결과 ─────────────────────────────────────────────────────

@dataclass
class TaskMeasurement:
    """단일 태스크 1회 실행 결과"""
    system_name: str          # "harmonet" | "langraph" | "crewai" etc.
    task_id: str
    task_category: str
    complexity: int

    success: bool             # 기대 키워드 충족 여부
    output: str               # 에이전트 출력 (첫 2000자)
    prompt_tokens: int        # 입력 토큰 추정
    completion_tokens: int    # 출력 토큰 추정
    total_tokens: int         # prompt + completion

    latency_seconds: float    # TTFC (Time To First Completion)
    error: Optional[str] = None
    raw_metadata: Dict = field(default_factory=dict)
    keyword_hits: int = 0
    keyword_total: int = 0
    keyword_hit_rate: float = 0.0
    strict_success: bool = False

    @property
    def cost_usd(self) -> float:
        """GPT-4o-mini 요금 기준 ($0.15/1M input, $0.60/1M output)"""
        return (self.prompt_tokens * 0.15 + self.completion_tokens * 0.60) / 1_000_000

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["cost_usd"] = self.cost_usd
        return d


@dataclass
class SystemBenchmarkResult:
    """한 시스템의 전체 태스크 결과 집계"""
    system_name: str
    measurements: List[TaskMeasurement] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if not self.measurements:
            return 0.0
        return sum(1 for m in self.measurements if m.success) / len(self.measurements)

    @property
    def avg_total_tokens(self) -> float:
        if not self.measurements:
            return 0.0
        return statistics.mean(m.total_tokens for m in self.measurements)

    @property
    def avg_latency(self) -> float:
        if not self.measurements:
            return 0.0
        return statistics.mean(m.latency_seconds for m in self.measurements)

    @property
    def total_cost_usd(self) -> float:
        return sum(m.cost_usd for m in self.measurements)

    @property
    def p99_latency(self) -> float:
        if not self.measurements:
            return 0.0
        latencies = sorted(m.latency_seconds for m in self.measurements)
        idx = max(0, math.ceil(len(latencies) * 0.99) - 1)
        return latencies[idx]

    @property
    def keyword_hit_rate(self) -> float:
        total = sum(m.keyword_total for m in self.measurements)
        if total <= 0:
            return 0.0
        return sum(m.keyword_hits for m in self.measurements) / total

    @property
    def strict_success_rate(self) -> float:
        if not self.measurements:
            return 0.0
        return sum(1 for m in self.measurements if m.strict_success) / len(self.measurements)

    def summary(self) -> Dict:
        return {
            "system": self.system_name,
            "tasks_run": len(self.measurements),
            "success_rate": round(self.success_rate, 4),
            "avg_total_tokens": round(self.avg_total_tokens, 1),
            "avg_latency_s": round(self.avg_latency, 3),
            "p99_latency_s": round(self.p99_latency, 3),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "keyword_hit_rate": round(self.keyword_hit_rate, 4),
            "strict_success_rate": round(self.strict_success_rate, 4),
        }


# ── 시스템 어댑터 프로토콜 ────────────────────────────────────────

class SystemAdapter(Protocol):
    """벤치마크 대상 시스템 인터페이스."""

    @property
    def name(self) -> str:
        """시스템 이름."""
        ...

    def run(self, task: BenchmarkTask) -> Dict[str, Any]:
        """
        태스크 실행 후 결과 dict 반환.

        반환 키:
            output (str): 에이전트 최종 출력
            prompt_tokens (int): 추정 입력 토큰
            completion_tokens (int): 추정 출력 토큰
            metadata (dict, optional): 시스템별 추가 정보
        """
        ...


# ── 성공 판정 ─────────────────────────────────────────────────────

def _count_tokens(text: str) -> int:
    """간단한 토큰 추정: 공백 분리 + 1.3 계수 (tiktoken 없는 환경용)."""
    try:
        # tiktoken이 있으면 사용
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, int(len(text.split()) * 1.3))


def _keyword_hits(output: str, expected_keywords: List[str]) -> int:
    if not output or not expected_keywords:
        return 0
    output_lower = output.lower()
    return sum(1 for kw in expected_keywords if kw.lower() in output_lower)


def _check_success(output: str, expected_keywords: List[str]) -> bool:
    """
    출력에서 기대 키워드 충족 여부 확인.
    대소문자 무시, 키워드 중 ≥ 50% 이상 포함 시 성공.
    """
    if not output or not expected_keywords:
        return False
    hits = _keyword_hits(output, expected_keywords)
    return hits >= max(1, len(expected_keywords) // 2)


def _check_strict_success(output: str, expected_keywords: List[str], threshold: float = 0.80) -> bool:
    if not output or not expected_keywords:
        return False
    return (_keyword_hits(output, expected_keywords) / len(expected_keywords)) >= threshold


# ── 메인 하네스 ───────────────────────────────────────────────────

class BenchmarkHarness:
    """
    공정한 벤치마크 환경.

    모든 시스템에 동일한 태스크를 동일한 순서로 제공하고
    측정 오차를 최소화하기 위해 warm-up + 3회 평균을 사용합니다.
    """

    def __init__(self, repeats: int = 1, warmup: int = 0):
        self.repeats = repeats
        self.warmup = warmup

    def run_task(
        self,
        adapter: SystemAdapter,
        task: BenchmarkTask,
    ) -> List[TaskMeasurement]:
        """단일 태스크를 `repeats`회 실행하여 측정 목록 반환."""
        measurements = []

        # 워밍업
        for _ in range(self.warmup):
            try:
                adapter.run(task)
            except Exception:
                pass

        for _ in range(self.repeats):
            t0 = time.perf_counter()
            error = None
            output = ""
            prompt_tokens = 0
            completion_tokens = 0
            metadata: Dict = {}

            try:
                result = adapter.run(task)
                output = str(result.get("output", ""))
                prompt_tokens = int(result.get("prompt_tokens", _count_tokens(task.prompt)))
                completion_tokens = int(result.get("completion_tokens", _count_tokens(output)))
                metadata = result.get("metadata", {})
            except Exception as exc:
                error = str(exc)
                prompt_tokens = _count_tokens(task.prompt)

            latency = time.perf_counter() - t0
            success = _check_success(output, task.expected_keywords) if not error else False
            keyword_total = len(task.expected_keywords)
            keyword_hits = _keyword_hits(output, task.expected_keywords) if not error else 0
            keyword_hit_rate = keyword_hits / keyword_total if keyword_total else 0.0
            strict_success = (
                _check_strict_success(output, task.expected_keywords)
                if not error else False
            )
            output_limit = int(os.getenv("BENCHMARK_OUTPUT_CHARS", "8000"))

            measurements.append(TaskMeasurement(
                system_name=adapter.name,
                task_id=task.id,
                task_category=task.category,
                complexity=task.complexity,
                success=success,
                output=output[:output_limit],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_seconds=round(latency, 4),
                error=error,
                raw_metadata=metadata,
                keyword_hits=keyword_hits,
                keyword_total=keyword_total,
                keyword_hit_rate=round(keyword_hit_rate, 4),
                strict_success=strict_success,
            ))

        return measurements

    def run_all(
        self,
        adapter: SystemAdapter,
        tasks: List[BenchmarkTask],
        verbose: bool = True,
    ) -> SystemBenchmarkResult:
        """모든 태스크 실행 후 집계 결과 반환."""
        result = SystemBenchmarkResult(system_name=adapter.name)
        total = len(tasks)

        for i, task in enumerate(tasks, 1):
            if verbose:
                print(f"  [{adapter.name}] ({i}/{total}) {task.id} ...", end=" ", flush=True)

            measurements = self.run_task(adapter, task)
            result.measurements.extend(measurements)

            if verbose:
                m = measurements[0]
                status = "✅" if m.success else "❌"
                print(f"{status} {m.total_tokens}tok {m.latency_seconds:.1f}s")

        return result


# ── 결과 저장 & 로드 ─────────────────────────────────────────────

def save_results(results: List[SystemBenchmarkResult], path: str) -> None:
    """결과를 JSON 파일로 저장."""
    data = {
        "systems": [
            {
                "summary": r.summary(),
                "measurements": [m.to_dict() for m in r.measurements],
            }
            for r in results
        ]
    }
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[Harness] 결과 저장: {path}")


def load_results(path: str) -> List[SystemBenchmarkResult]:
    """JSON 파일에서 결과 로드."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    results = []
    for sys_data in data["systems"]:
        r = SystemBenchmarkResult(system_name=sys_data["summary"]["system"])
        for m_data in sys_data["measurements"]:
            m_data.pop("cost_usd", None)  # computed property
            r.measurements.append(TaskMeasurement(**m_data))
        results.append(r)
    return results
