"""
benchmark/runloop.py — 러너 공통 실행 루프 (Week2-D1). bcb_g1 / mbppplus_g1 / lcb_g1 이 공유한다.

안전장치 (호출 순서대로):
  1. 유료 백엔드(HARMONET_LLM_BACKEND != mock)는 예산 원장(HARMONET_BUDGET_CAP) 없이는 돌지 않는다 → RuntimeError, 호출 0회.
  2. 호출 전 예약: projected = 입력 추정 + max_tokens × 출력단가. 예약 실패 → BudgetStop → 부분 결과 저장(stopped_reason="budget") → 종료 코드 2.
  3. 호출 후 실측 가산. 행의 cost_usd 가 None(미측정) → 저장 후 중단(stopped_reason="unpriced") → 종료 코드 2.
  4. 채점 인프라 장애(결과에 infra=True) → 저장 후 즉시 중단(stopped_reason="infra") → 종료 코드 2. 후보 원인 aborted 는 계속 진행.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from harmonet.budget import Budget, BudgetStop, projected_cost
from harmonet.pricing import cost_usd
from harmonet.trace import meter_delta, model_used
from harmonet.usage import METER

EXIT_STOPPED = 2


class InfraStop(RuntimeError):
    """채점 인프라 장애(infra=True)를 verify 직후 그 자리에서 알린다 (F1-e). partial 에 그때까지의 결과를 실어 부분 저장한다."""

    def __init__(self, msg: str, partial: Optional[Dict[str, Any]] = None):
        super().__init__(msg)
        self.partial = partial


def require_budget(budget: Optional[Budget]) -> None:
    backend = os.getenv("HARMONET_LLM_BACKEND", "").lower()
    if budget is None and backend not in ("mock", "mock-scenario"):
        raise RuntimeError("[runloop] 유료 백엔드는 예산 원장 없이 돌지 않는다 — HARMONET_BUDGET_CAP(USD) 와 HARMONET_BUDGET_ID 를 설정하라. 호출 0회.")


def budgeted_generate(client, budget: Optional[Budget], prompt: str, system_prompt: str, role: Optional[str] = None, note: str = ""
                      ) -> Tuple[str, Dict[str, Any], Optional[float], int]:
    """(output, cost_dict, cost_usd, wall_ms). 예약 실패면 BudgetStop — LLM 을 호출하지 않는다. role 은 기본 client.role (METER 태그)."""
    role = role or getattr(client, "role", "builder")
    max_tokens = int(getattr(client, "max_tokens", None) or os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
    projected = projected_cost(getattr(client, "model", None), len(prompt) + len(system_prompt or ""), max_tokens) if budget else 0.0
    if budget and not budget.reserve(projected, note):
        raise BudgetStop(f"예산 상한: projected ${projected:.4f} 를 더하면 cap ${budget.cap} 초과 ({budget.path})")
    before = METER.snapshot(role)
    t0 = time.perf_counter()
    try:
        output = client.generate(prompt, system_prompt=system_prompt)
    except BaseException:
        if budget:
            budget.commit(projected, 0.0, note + " (call raised)")
        raise
    wall = int((time.perf_counter() - t0) * 1000)
    cost = meter_delta(before, METER.snapshot(role), wall_ms=wall)
    usd = cost_usd(model_used(role, client), cost)[0]
    if budget:
        budget.commit(projected, usd, note)
    return output or "", cost, usd, wall


def run_loop(ids: List[str], run_task: Callable[[str], Dict[str, Any]], write: Callable[[List[Dict[str, Any]], Optional[str]], Any],
             budget: Optional[Budget], label: str = "single") -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """과제를 순서대로. 중단 사유가 생기면 부분 결과를 저장하고 SystemExit(2)."""
    rows: List[Dict[str, Any]] = []
    stopped: Optional[str] = None
    for k, tid in enumerate(ids, 1):
        try:
            r = run_task(tid)
        except BudgetStop as e:
            stopped = "budget"
            print(f"[{label}] {k}/{len(ids)} {tid}: {e}", flush=True)
            break
        except InfraStop as e:
            stopped = "infra"
            if e.partial:
                rows.append(e.partial)
            if budget:
                budget.stop("infra")
            print(f"[{label}] {k}/{len(ids)} {tid}: {e}", flush=True)
            break
        rows.append(r)
        print(f"[{label}] {k}/{len(ids)} {tid} " + r.get("line", "") + f" ${r['cost_usd']}", flush=True)
        if r["cost_usd"] is None:
            stopped = "unpriced"
            if budget:
                budget.stop("unpriced")
            break
        if r.get("infra"):
            stopped = "infra"
            if budget:
                budget.stop("infra")
            break
    write(rows, stopped)
    if stopped:
        print(f"[{label}] 중단: {stopped} ({len(rows)}/{len(ids)} 저장)", flush=True)
        raise SystemExit(EXIT_STOPPED)
    return rows, None
