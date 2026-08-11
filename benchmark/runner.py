"""
benchmark/runner.py — 벤치마크 실행 CLI
=========================================
HarmoNet과 LangGraph를 동일한 태스크에서 비교 실행합니다.

사용법:
    # 전체 20개 태스크 (API 키 없으면 Mock LLM)
    python -X utf8 -m benchmark.runner

    # 특정 카테고리, 5개 태스크, 3회 반복
    python -X utf8 -m benchmark.runner --categories code_gen debugging --limit 5 --repeats 3

    # LangGraph만 스킵 (HarmoNet 단독)
    python -X utf8 -m benchmark.runner --skip-langraph

    # 결과를 my_results.json에 저장
    python -X utf8 -m benchmark.runner --output my_results.json

환경변수:
    OPENAI_API_KEY     — 설정 시 GPT-4o-mini 사용
    ANTHROPIC_API_KEY  — 설정 시 Claude Haiku 사용
    (둘 다 없으면 Mock LLM — 구조 테스트 전용)
"""

import sys
import os
import time
import argparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from benchmark.tasks import get_tasks
from benchmark.harness import BenchmarkHarness, save_results
from benchmark.agents_harmonet import HarmoNetAdapter
from benchmark.report import print_comparison_table


def _sep(title: str = "", width: int = 72, char: str = "─"):
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{char * pad} {title} {char * pad}")
    else:
        print(char * width)


def main():
    parser = argparse.ArgumentParser(
        description="HarmoNet vs LangGraph 벤치마크",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--categories", nargs="*",
        choices=["code_gen", "api_design", "debugging", "refactoring"],
        default=None, help="실행할 카테고리 (기본: 전체)",
    )
    parser.add_argument("--limit", type=int, default=None, help="태스크 수 제한")
    parser.add_argument("--repeats", type=int, default=1, help="태스크당 반복 횟수")
    parser.add_argument("--max-complexity", type=int, default=3, choices=[1, 2, 3],
                        help="최대 복잡도 필터 (기본: 3)")
    parser.add_argument("--skip-langraph", action="store_true", help="LangGraph 스킵")
    parser.add_argument("--skip-harmonet", action="store_true", help="HarmoNet 스킵")
    parser.add_argument("--output", default="benchmark_results.json", help="결과 저장 경로")
    parser.add_argument("--no-report", action="store_true", help="실행 후 리포트 출력 안 함")
    parser.add_argument("--harmonet-ticks", type=int, default=5, help="HarmoNet 틱 수")
    args = parser.parse_args()

    _sep("HarmoNet 산업 도입 벤치마크 — Phase 1 Go/No-Go", char="═")

    # ── 태스크 로드 ──────────────────────────────────────────────
    tasks = get_tasks(
        categories=args.categories,
        max_complexity=args.max_complexity,
        limit=args.limit,
    )
    print(f"\n태스크: {len(tasks)}개  |  반복: {args.repeats}회  |  HarmoNet 틱: {args.harmonet_ticks}")
    print(f"카테고리: {', '.join(set(t.category for t in tasks))}")

    # API 키 감지
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_runyourai = bool(os.environ.get("RUNYOURAI_API_KEY"))
    if has_openai:
        print("🔑 OPENAI_API_KEY 감지 → GPT-4o-mini 사용")
    elif has_anthropic:
        print("🔑 ANTHROPIC_API_KEY 감지 → Claude Haiku 사용")
    elif has_runyourai:
        model = os.environ.get("RUNYOURAI_MODEL", "runyour/free")
        print(f"🔑 RUNYOURAI_API_KEY 감지 → RunYourAI 사용 ({model})")
    else:
        print("⚠  API 키 없음 → Mock LLM (구조 테스트 전용, 성능 비교 불가)")

    harness = BenchmarkHarness(repeats=args.repeats)
    all_results = []

    # ── HarmoNet 실행 ────────────────────────────────────────────
    if not args.skip_harmonet:
        _sep("HarmoNet 실행 중")
        harmonet_adapter = HarmoNetAdapter(ticks=args.harmonet_ticks)
        t0 = time.perf_counter()
        harmonet_result = harness.run_all(harmonet_adapter, tasks, verbose=True)
        elapsed = time.perf_counter() - t0
        all_results.append(harmonet_result)
        s = harmonet_result.summary()
        print(f"\n  완료: {elapsed:.1f}s | 성공률={s['success_rate']*100:.1f}% | "
              f"평균토큰={s['avg_total_tokens']:.0f} | 비용=${s['total_cost_usd']:.4f}")

    # ── LangGraph 실행 ────────────────────────────────────────────
    if not args.skip_langraph:
        from benchmark.agents_langraph import LangGraphAdapter

        _sep("LangGraph 실행 중")
        langraph_adapter = LangGraphAdapter()
        t0 = time.perf_counter()
        langraph_result = harness.run_all(langraph_adapter, tasks, verbose=True)
        elapsed = time.perf_counter() - t0
        all_results.append(langraph_result)
        s = langraph_result.summary()
        print(f"\n  완료: {elapsed:.1f}s | 성공률={s['success_rate']*100:.1f}% | "
              f"평균토큰={s['avg_total_tokens']:.0f} | 비용=${s['total_cost_usd']:.4f}")

    # ── 결과 저장 ────────────────────────────────────────────────
    save_results(all_results, args.output)

    # ── 비교 리포트 ──────────────────────────────────────────────
    if not args.no_report:
        print_comparison_table(all_results)

    _sep("완료", char="═")


if __name__ == "__main__":
    main()
