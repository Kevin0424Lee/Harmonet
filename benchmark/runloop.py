"""
benchmark/runloop.py — 러너 공통 실행 루프 (Week2-D1). bcb_g1 / mbppplus_g1 / lcb_g1 이 공유한다.

안전장치 (호출 순서대로):
  1. 유료 백엔드(HARMONET_LLM_BACKEND != mock)는 예산 원장(HARMONET_BUDGET_CAP) 없이는 돌지 않는다 → RuntimeError, 호출 0회.
  2. 호출 전 예약: projected = count_tokens 실측 입력 × 1.10 + max_tokens × 출력단가 (F2). 세지 못하면 호출 안 함. 예약 실패 → BudgetStop("budget").
     호출 예외 → 예약액을 지출로 확정(unknown_cost) → BudgetStop("unknown_cost"). 커밋 후 spent > cap → BudgetStop("cap_exceeded_post").
     재시도(J2·K2): 최대 MAX_ATTEMPTS 회, **시도마다** 예약·확정, 원장 1건씩. SDK 재시도는 0 (llm.AnthropicClient max_retries=0) — 원장에 안 보이는 HTTP 호출은 없다.
     시도별 귀속 (K2, PREREG v4 §5 와 같은 문장):
       (a) 성공 시도: 실측 비용.
       (b) 요금 없음이 확실한 실패(HTTP 429·400·401·5xx 응답 — 서버가 처리 전 거부): actual=0, attempt_failed_unbilled, 예약 해제, 호출 수 포함.
           429/5xx 는 재시도, 400/401 은 재시도 없이 BudgetStop("call_failed") (설정 오류 — 부분 결과 저장 후 중단).
       (c) 처리 여부 불명 실패(타임아웃·연결 끊김 — 응답 없음): 예약액을 보수적으로 확정(unknown_cost), n_unknown 포함. 같은 과제에서 (c) 1회면 재시도 계속,
           2회면 그 arm 중단(CallAborted → 호출자는 기존 산출물로 종료). 실패 시도가 unknown_cost=False 로 남는 경로는 없다.
     어느 경우든 부분 결과 저장(stopped_reason) → 종료 코드 2.
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
MAX_ATTEMPTS, RETRY_BASE_DELAY_S, MAX_UNKNOWN_PER_TASK = 3, 2.0, 2


class CallAborted(RuntimeError):
    """같은 과제에서 처리 여부 불명 실패(c)가 MAX_UNKNOWN_PER_TASK 회 — 이 arm 은 더 호출하지 않는다. usd = 확정된 예약액 합, attempts = 시도 기록."""

    def __init__(self, msg: str, usd: float, attempts: list):
        super().__init__(msg)
        self.usd, self.attempts = usd, attempts


def classify_failure(exc: BaseException) -> str:
    """(b) 'unbilled_retry' = HTTP 429/5xx 응답, 'unbilled_fatal' = 그 밖의 HTTP 응답(400/401/403/404…); (c) 'unknown' = 응답 없음(타임아웃·연결 끊김·기타)."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return "unbilled_retry" if (status == 429 or status >= 500) else "unbilled_fatal"
    return "unknown"


class InfraStop(RuntimeError):
    """채점 인프라 장애(infra=True)를 verify 직후 그 자리에서 알린다 (F1-e). partial 에 그때까지의 결과를 실어 부분 저장한다."""

    def __init__(self, msg: str, partial: Optional[Dict[str, Any]] = None):
        super().__init__(msg)
        self.partial = partial


def require_budget(budget: Optional[Budget]) -> None:
    backend = os.getenv("HARMONET_LLM_BACKEND", "").lower()
    if budget is None and backend not in ("mock", "mock-scenario"):
        raise RuntimeError("[runloop] 유료 백엔드는 예산 원장 없이 돌지 않는다 — HARMONET_BUDGET_CAP(USD) 와 HARMONET_BUDGET_ID 를 설정하라. 호출 0회.")


def budgeted_generate(client, budget: Optional[Budget], prompt: str, system_prompt: str, role: Optional[str] = None, note: str = "",
                      unknown_counter: Optional[Dict[str, int]] = None) -> Tuple[str, Dict[str, Any], Optional[float], int]:
    """(output, cost_dict, cost_usd, wall_ms). 예약 실패면 BudgetStop — LLM 을 호출하지 않는다. role 은 기본 client.role (METER 태그).
    cost_usd = 성공 시도 실측 + (c) 시도의 확정 예약액 (arm 비용·잔여 예산·원장이 같은 수를 본다). cost_dict["attempts"] 에 시도별 귀속 기록.
    unknown_counter = 과제 수준 (c) 카운터({"n": k}); 없으면 이 호출만 센다."""
    role = role or getattr(client, "role", "builder")
    max_tokens = int(getattr(client, "max_tokens", None) or os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
    projected = 0.0
    if budget:
        projected = projected_cost(getattr(client, "model", None), input_tokens(client, prompt, system_prompt), max_tokens)
    call = getattr(client, "generate_once", None) or client.generate      # 클라이언트 내부 재시도 우회 — 시도마다 원장에 남긴다 (J2)
    unknown_counter = unknown_counter if unknown_counter is not None else {"n": 0}
    attempts: List[Dict[str, Any]] = []
    unknown_usd = 0.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if budget and not budget.reserve(projected, f"{note} (attempt {attempt})" if attempt > 1 else note):
            raise BudgetStop(f"예산 상한: projected ${projected:.4f} 를 더하면 cap ${budget.cap} 초과 ({budget.path})", "budget")
        before = METER.snapshot(role)
        t0 = time.perf_counter()
        try:
            output = call(prompt, system_prompt=system_prompt)
            break
        except BaseException as exc:
            kind = classify_failure(exc)
            tag = f"{note} (attempt {attempt} {kind}: {type(exc).__name__} {getattr(exc, 'status_code', '')})"
            if kind == "unknown":                         # (c) 예약액 확정, unknown_cost=True — 중단은 규칙(과제당 2회)으로
                if budget:
                    budget.commit(projected, None, tag, unknown_cost=True, stop=False)
                unknown_usd += projected
                unknown_counter["n"] += 1
                attempts.append({"attempt": attempt, "kind": kind, "usd": projected, "unknown_cost": True, "exc": type(exc).__name__})
                if unknown_counter["n"] >= MAX_UNKNOWN_PER_TASK:
                    raise CallAborted(f"같은 과제에서 처리 여부 불명 실패 {unknown_counter['n']}회 — 이 arm 중단 ({exc})", unknown_usd, attempts) from exc
            else:                                         # (b) 요금 없음 확실: actual 0, 예약 해제, 호출 수 포함
                if budget:
                    budget.commit(projected, 0.0, tag, attempt_failed_unbilled=True)
                attempts.append({"attempt": attempt, "kind": kind, "usd": 0.0, "unknown_cost": False, "attempt_failed_unbilled": True,
                                 "status": getattr(exc, "status_code", None), "exc": type(exc).__name__})
                if kind == "unbilled_fatal":
                    raise BudgetStop(f"호출 실패(HTTP {getattr(exc, 'status_code', '?')}, 요금 없음) — 재시도 없이 중단: {exc}", "call_failed") from exc
            if attempt < MAX_ATTEMPTS:
                delay = RETRY_BASE_DELAY_S * 2 ** (attempt - 1)
                print(f"[runloop] 재시도 {attempt}/{MAX_ATTEMPTS} ({kind}, {delay:.0f}s): {str(exc)[:80]}", flush=True)
                time.sleep(delay)
                continue
            raise BudgetStop(f"호출 {MAX_ATTEMPTS}회 전부 실패 ({kind}) — 중단: {exc}", "call_failed" if kind != "unknown" else "unknown_cost") from exc
    wall = int((time.perf_counter() - t0) * 1000)
    cost = meter_delta(before, METER.snapshot(role), wall_ms=wall)
    measured = cost_usd(model_used(role, client), cost)[0]
    attempts.append({"attempt": len(attempts) + 1, "kind": "success", "usd": measured, "unknown_cost": False})
    cost["attempts"] = attempts
    cost["n_unknown_attempts"] = sum(a["unknown_cost"] for a in attempts)
    cost["unknown_reserved_usd"] = round(unknown_usd, 10)
    cost["llm_calls"] = len(attempts)                     # HTTP 시도 수 == 원장 건수
    usd = None if measured is None else round(measured + unknown_usd, 10)
    if budget:
        st = budget.commit(projected, measured, note)
        if st["stopped_reason"] == "cap_exceeded_post":
            raise BudgetStop(f"커밋 후 spent ${st['spent']:.4f} > cap ${st['cap']} — 중단 (사후 장치)", "cap_exceeded_post")
    return output or "", cost, usd, wall


def input_tokens(client, prompt: str, system_prompt: Optional[str]) -> int:
    """백엔드의 무료 count_tokens 로 입력 토큰을 센다. 세지 못하면 RuntimeError — 호출하지 않는다 (조용한 추정 대체 금지, F2)."""
    fn = getattr(client, "count_input_tokens", None)
    if fn is None:
        if str(getattr(client, "model", "")).startswith("mock"):
            return 0                                      # $0 백엔드: 예약 0
        raise RuntimeError(f"[runloop] {type(client).__name__} 은 count_tokens 를 지원하지 않아 입력 토큰을 셀 수 없다 — 호출하지 않는다")
    try:
        return int(fn(prompt, system_prompt))
    except Exception as exc:
        raise RuntimeError(f"[runloop] count_tokens 실패 — 호출하지 않는다: {exc}") from exc


def run_loop(ids: List[str], run_task: Callable[[str], Dict[str, Any]], write: Callable[[List[Dict[str, Any]], Optional[str]], Any],
             budget: Optional[Budget], label: str = "single") -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """과제를 순서대로. 중단 사유가 생기면 부분 결과를 저장하고 SystemExit(2)."""
    rows: List[Dict[str, Any]] = []
    stopped: Optional[str] = None
    for k, tid in enumerate(ids, 1):
        try:
            r = run_task(tid)
        except BudgetStop as e:
            stopped = e.reason                            # budget | cap_exceeded_post | unknown_cost | call_failed
            if getattr(e, "partial", None):               # J2: 현재 과제에서 이미 끝난 arm 행은 부분 결과에 포함
                rows.append(e.partial)
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
