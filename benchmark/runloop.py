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


def _attempt_totals(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """시도 기록 → 성공 실측 / 불명 시도의 보수적 예약 귀속 / 합계 (L1-7: 귀속액을 실측 청구액으로 표기하지 않는다)."""
    measured = [a["usd"] for a in attempts if a["kind"] == "success"]
    unknown = [a["usd"] for a in attempts if a["unknown_cost"]]
    m = None if any(v is None for v in measured) else round(sum(measured), 10)
    u = round(sum(unknown), 10)
    return {"measured_usd": m, "unknown_reserved_usd": u, "cost_usd": None if m is None else round(m + u, 10),
            "n_attempts": len(attempts), "n_unknown_attempts": len(unknown), "n_unbilled_failed": sum(bool(a.get("attempt_failed_unbilled")) for a in attempts)}


class CallAborted(RuntimeError):
    """이 arm 은 더 호출하지 않는다. reason: "unknown_cost_x2" (같은 과제에서 (c) MAX_UNKNOWN_PER_TASK 회) | "arm_budget" (arm 잔여 예산으로 최소 출력 예산 미달, L1).
    usd = 이 호출에서 확정된 예약액 합, attempts = 시도 기록 (성공 없이 끝난 시도도 보존, L5)."""

    def __init__(self, msg: str, usd: float, attempts: list, reason: str = "unknown_cost_x2"):
        super().__init__(msg)
        self.attempts, self.reason = attempts, reason
        tot = _attempt_totals(attempts)                     # M3: 예외 비용은 공통 집계 — cost_usd = 실측 + 불명 예약 귀속 (usd 인자는 호환용, 집계값이 우선)
        self.usd, self.measured_usd, self.unknown_reserved_usd = tot["cost_usd"], tot["measured_usd"], tot["unknown_reserved_usd"]


class ArmBudget:
    """arm 별 잔여 예산 (L1): 시도 직전마다 max_tokens = max_tokens_fn(remaining) 을 다시 계산하고, (c) 시도의 예약액·성공 실측을 즉시 차감한다."""

    def __init__(self, remaining_usd: float, max_tokens_fn: Callable[[float], int], min_max_tokens: int, cap_tokens: int):
        self.remaining_usd, self.max_tokens_fn, self.min_max_tokens, self.cap_tokens = float(remaining_usd), max_tokens_fn, int(min_max_tokens), int(cap_tokens)

    def max_tokens(self) -> int:
        return min(int(self.max_tokens_fn(self.remaining_usd)), self.cap_tokens)


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
                      unknown_counter: Optional[Dict[str, int]] = None, arm: Optional[ArmBudget] = None) -> Tuple[str, Dict[str, Any], Optional[float], int]:
    """(output, cost_dict, cost_usd, wall_ms). 예약 실패면 BudgetStop — LLM 을 호출하지 않는다. role 은 기본 client.role (METER 태그).
    cost_usd = 성공 시도 실측 + (c) 시도의 확정 예약액; cost_dict 에 measured_usd / unknown_reserved_usd / attempts(시도별, max_tokens 포함) 를 따로 둔다.
    arm(ArmBudget, L1): 모든 시도 직전에 전체 원장 **과** arm 잔여를 함께 검사 — max_tokens 를 갱신된 잔여로 다시 계산, 최소 출력 예산 미달이면 CallAborted("arm_budget").
    어떤 중단(예약 거부·재시도 소진·치명적 오류·불명 2회·arm 예산)이든 그때까지의 시도 기록·확정 비용을 예외에 실어 보낸다 (L5).
    unknown_counter = 과제 수준 (c) 카운터({"n": k}); 없으면 이 호출만 센다."""
    role = role or getattr(client, "role", "builder")
    call = getattr(client, "generate_once", None) or client.generate      # 클라이언트 내부 재시도 우회 — 시도마다 원장에 남긴다 (J2); SDK 재시도 0 (K2)
    unknown_counter = unknown_counter if unknown_counter is not None else {"n": 0}
    attempts: List[Dict[str, Any]] = []
    n_in = input_tokens(client, prompt, system_prompt) if budget else 0
    old_mt = getattr(client, "max_tokens", None)

    def _stop(msg: str, reason: str, cause: BaseException = None):
        e = BudgetStop(msg, reason)
        tot = _attempt_totals(attempts)                     # M3: cap_exceeded_post 처럼 성공 실측이 이미 확정된 뒤의 중단도 실측을 잃지 않는다
        e.attempts, e.usd, e.measured_usd, e.unknown_reserved_usd = attempts, tot["cost_usd"], tot["measured_usd"], tot["unknown_reserved_usd"]
        if cause is not None:
            e.__cause__ = cause
        return e

    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if arm is not None:                               # L1: arm 잔여로 max_tokens 재계산, 미달이면 추가 호출 없음
                mt = arm.max_tokens()
                if mt < arm.min_max_tokens:
                    raise CallAborted(f"arm 잔여 ${arm.remaining_usd:.5f} 로 max_tokens={mt} < {arm.min_max_tokens} — 추가 호출 없음", _attempt_totals(attempts)["unknown_reserved_usd"],
                                      attempts, reason="arm_budget")
                client.max_tokens = mt
            else:
                mt = int(getattr(client, "max_tokens", None) or os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
            projected = projected_cost(getattr(client, "model", None), n_in, mt) if budget else 0.0
            if budget and not budget.reserve(projected, f"{note} (attempt {attempt})" if attempt > 1 else note):
                raise _stop(f"예산 상한(전체 원장): projected ${projected:.4f} 를 더하면 cap ${budget.cap} 초과 ({budget.path})", "budget")
            before = METER.snapshot(role)
            t0 = time.perf_counter()
            try:
                output = call(prompt, system_prompt=system_prompt)
            except BaseException as exc:
                kind = classify_failure(exc)
                tag = f"{note} (attempt {attempt} {kind}: {type(exc).__name__} {getattr(exc, 'status_code', '')})"
                if kind == "unknown":                         # (c) 예약액 확정, unknown_cost=True — arm 잔여에도 즉시 반영 (L1-2)
                    if budget:
                        budget.commit(projected, None, tag, unknown_cost=True, stop=False)
                    if arm is not None:
                        arm.remaining_usd -= projected
                    unknown_counter["n"] += 1
                    attempts.append({"attempt": attempt, "kind": kind, "usd": projected, "unknown_cost": True, "max_tokens": mt, "exc": type(exc).__name__})
                    if unknown_counter["n"] >= MAX_UNKNOWN_PER_TASK:
                        raise CallAborted(f"같은 과제에서 처리 여부 불명 실패 {unknown_counter['n']}회 — 이 arm 중단 ({exc})",
                                          _attempt_totals(attempts)["unknown_reserved_usd"], attempts, reason="unknown_cost_x2") from exc
                else:                                         # (b) 요금 없음 확실: actual 0, 예약 해제, 호출 수 포함
                    if budget:
                        budget.commit(projected, 0.0, tag, attempt_failed_unbilled=True)
                    attempts.append({"attempt": attempt, "kind": kind, "usd": 0.0, "unknown_cost": False, "attempt_failed_unbilled": True, "max_tokens": mt,
                                     "status": getattr(exc, "status_code", None), "exc": type(exc).__name__})
                    if kind == "unbilled_fatal":
                        raise _stop(f"호출 실패(HTTP {getattr(exc, 'status_code', '?')}, 요금 없음) — 재시도 없이 중단: {exc}", "call_failed", exc)
                if attempt < MAX_ATTEMPTS:
                    delay = RETRY_BASE_DELAY_S * 2 ** (attempt - 1)
                    print(f"[runloop] 재시도 {attempt}/{MAX_ATTEMPTS} ({kind}, {delay:.0f}s): {str(exc)[:80]}", flush=True)
                    time.sleep(delay)
                    continue
                raise _stop(f"호출 {MAX_ATTEMPTS}회 전부 실패 ({kind}) — 중단: {exc}", "call_failed" if kind != "unknown" else "unknown_cost", exc)
            wall = int((time.perf_counter() - t0) * 1000)
            cost = meter_delta(before, METER.snapshot(role), wall_ms=wall)
            measured = cost_usd(model_used(role, client), cost)[0]
            attempts.append({"attempt": attempt, "kind": "success", "usd": measured, "unknown_cost": False, "max_tokens": mt})
            tot = _attempt_totals(attempts)
            cost.update({"attempts": attempts, "n_unknown_attempts": tot["n_unknown_attempts"], "unknown_reserved_usd": tot["unknown_reserved_usd"],
                         "measured_usd": measured, "llm_calls": len(attempts)})     # HTTP 시도 수 == 원장 건수
            if arm is not None and measured is not None:
                arm.remaining_usd -= measured
            if budget:
                st = budget.commit(projected, measured, note)
                if st["stopped_reason"] == "cap_exceeded_post":
                    raise _stop(f"커밋 후 spent ${st['spent']:.4f} > cap ${st['cap']} — 중단 (사후 장치)", "cap_exceeded_post")
            return output or "", cost, tot["cost_usd"], wall
    finally:
        if old_mt is not None:
            client.max_tokens = old_mt


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
            if getattr(e, "partial", None):               # J2/L5: 현재 과제에서 이미 끝난 arm 행 + 미완료 arm 의 시도 기록을 부분 결과에 포함
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
