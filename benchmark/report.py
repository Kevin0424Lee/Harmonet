"""
benchmark/report.py — 벤치마크 결과 비교 리포트 생성
======================================================

사용법:
    python -X utf8 -m benchmark.report                        # 최신 results.json
    python -X utf8 -m benchmark.report --file results.json    # 지정 파일
    python -X utf8 -m benchmark.report --file r.json --csv    # CSV도 저장
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from benchmark.harness import load_results, SystemBenchmarkResult


def _bar(value: float, max_value: float, width: int = 20) -> str:
    if max_value <= 0:
        return " " * width
    filled = int(width * min(1.0, value / max_value))
    return "█" * filled + "░" * (width - filled)


def print_comparison_table(results: List[SystemBenchmarkResult]) -> None:
    """시스템 간 비교 표 출력."""
    if not results:
        print("결과 없음.")
        return

    sep = "─" * 80
    print(f"\n{'═' * 80}")
    print(f"  HarmoNet vs LangGraph 벤치마크 비교 리포트")
    print(f"{'═' * 80}")

    summaries = [r.summary() for r in results]

    # ── 요약 테이블 ────────────────────────────────────────────
    print(
        f"\n{'시스템':<28} {'성공률':>8} {'strict80':>9} {'키워드':>8} "
        f"{'평균 토큰':>10} {'평균 지연(s)':>12} {'p99(s)':>9} {'비용($)':>10}"
    )
    print(sep)
    for s in summaries:
        print(
            f"  {s['system']:<26} "
            f"{s['success_rate']*100:>7.1f}% "
            f"{s.get('strict_success_rate', 0)*100:>8.1f}% "
            f"{s.get('keyword_hit_rate', 0)*100:>7.1f}% "
            f"{s['avg_total_tokens']:>10.0f} "
            f"{s['avg_latency_s']:>12.3f} "
            f"{s['p99_latency_s']:>9.3f} "
            f"{s['total_cost_usd']:>10.6f}"
        )

    # ── HarmoNet vs LangGraph 델타 ──────────────────────────
    harmonet = next((r for r in results if r.system_name == "harmonet"), None)
    langraph = next((r for r in results if "langraph" in r.system_name), None)

    if harmonet and langraph:
        print(f"\n{sep}")
        print("  핵심 가설 검증 (HarmoNet Phase 1 Go/No-Go 기준)")
        print(sep)

        h = harmonet.summary()
        l = langraph.summary()

        # G1-1: 토큰 비용 ≤ LangGraph × 0.7
        tok_ratio = h["avg_total_tokens"] / max(1, l["avg_total_tokens"])
        g1_1 = tok_ratio <= 0.70
        print(f"  G1-1 토큰 비용: HarmoNet={h['avg_total_tokens']:.0f} / LangGraph={l['avg_total_tokens']:.0f} "
              f"= {tok_ratio:.2%}  {'✅ PASS (≤70%)' if g1_1 else '❌ FAIL (>70%)'}")

        # G1-2: 성공률 ≥ LangGraph - 5%p
        success_gap = h["success_rate"] - l["success_rate"]
        g1_2 = success_gap >= -0.05
        print(f"  G1-2 성공률:    HarmoNet={h['success_rate']*100:.1f}% / LangGraph={l['success_rate']*100:.1f}% "
              f"= {success_gap*100:+.1f}%p  {'✅ PASS (≥-5%p)' if g1_2 else '❌ FAIL (<-5%p)'}")
        strict_gap = h.get("strict_success_rate", 0) - l.get("strict_success_rate", 0)
        print(f"       strict80:   HarmoNet={h.get('strict_success_rate', 0)*100:.1f}% / "
              f"LangGraph={l.get('strict_success_rate', 0)*100:.1f}% = {strict_gap*100:+.1f}%p")
        print(f"       키워드 적중: HarmoNet={h.get('keyword_hit_rate', 0)*100:.1f}% / "
              f"LangGraph={l.get('keyword_hit_rate', 0)*100:.1f}%")

        # G1-3: p99 latency ≤ 30s (단일 태스크 기준)
        g1_3 = h["p99_latency_s"] <= 30.0
        print(f"  G1-3 p99 지연:  HarmoNet={h['p99_latency_s']:.1f}s "
              f"{'✅ PASS (≤30s)' if g1_3 else '❌ FAIL (>30s)'}")

        gate_passed = sum([g1_1, g1_2, g1_3])
        print(f"\n  {'═'*40}")
        print(f"  G1 게이트:  {gate_passed}/3 기준 충족  "
              f"{'✅ GO (≥2/3)' if gate_passed >= 2 else '❌ NO-GO (<2/3) → 프로젝트 중단 권고'}")
        print(f"  {'═'*40}")

    # ── 카테고리별 성공률 ───────────────────────────────────
    print(f"\n{sep}")
    print("  카테고리별 성공률")
    print(sep)
    categories = sorted(set(m.task_category for r in results for m in r.measurements))
    for cat in categories:
        print(f"\n  {cat}:")
        for r in results:
            cat_ms = [m for m in r.measurements if m.task_category == cat]
            if cat_ms:
                rate = sum(1 for m in cat_ms if m.success) / len(cat_ms)
                strict = sum(1 for m in cat_ms if getattr(m, "strict_success", False)) / len(cat_ms)
                kw_total = sum(getattr(m, "keyword_total", 0) for m in cat_ms)
                kw_hits = sum(getattr(m, "keyword_hits", 0) for m in cat_ms)
                kw_rate = kw_hits / kw_total if kw_total else 0.0
                bar = _bar(rate, 1.0, 16)
                print(
                    f"    {r.system_name:<20} {bar} success={rate*100:.1f}% "
                    f"strict80={strict*100:.1f}% keyword={kw_rate*100:.1f}%"
                )

    print(f"\n{'═' * 80}\n")


def save_csv(results: List[SystemBenchmarkResult], path: str) -> None:
    """측정 결과를 CSV로 저장."""
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "system", "task_id", "category", "complexity",
            "success", "prompt_tokens", "completion_tokens", "total_tokens",
            "latency_s", "keyword_hits", "keyword_total", "keyword_hit_rate",
            "strict_success", "cost_usd", "error",
        ])
        for r in results:
            for m in r.measurements:
                writer.writerow([
                    m.system_name, m.task_id, m.task_category, m.complexity,
                    m.success, m.prompt_tokens, m.completion_tokens, m.total_tokens,
                    m.latency_seconds, m.keyword_hits, m.keyword_total,
                    m.keyword_hit_rate, m.strict_success,
                    round(m.cost_usd, 8), m.error or "",
                ])
    print(f"[Report] CSV 저장: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HarmoNet 벤치마크 비교 리포트")
    parser.add_argument("--file", default="benchmark_results.json", help="결과 JSON 파일")
    parser.add_argument("--csv", action="store_true", help="CSV도 저장")
    args = parser.parse_args()

    if not Path(args.file).exists():
        print(f"[오류] 파일 없음: {args.file}")
        print("먼저 python -m benchmark.runner 를 실행해 주세요.")
        sys.exit(1)

    results = load_results(args.file)
    print_comparison_table(results)

    if args.csv:
        csv_path = args.file.replace(".json", ".csv")
        save_csv(results, csv_path)
