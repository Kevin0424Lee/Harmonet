"""
benchmark/arms.py — 6 arm 실행기 (Week2-D5 → F1 개정, 풀 무관 인프라). 설계: docs/week2_design_draft.md §2·§3·§6·§7·§8.

저장 계층 (F1-c): evidence/week2/<run_id>/<task_id>/s0/{artifact.py, verify_visible.json, prompt_context.json, decision_signals.json, sha256.txt}
  s0 는 **한 번만** 생성한다 — 있으면 sha256 을 대조해 재사용(덮어쓰기 금지, 불일치면 RuntimeError).
  arm 반복은 <task_id>/<arm>/rep<r>/{artifact_n.py, verify_visible_n.json, result.json}. result.json 이 있으면 그 (arm, rep) 은 건너뛴다(멱등).
과제마다:
  s0  = A(builder) 1회 build → verify_visible → 스냅샷. 계속 arm 은 **디스크의 s0 를 읽어** 재개(메모리 상태 재사용 금지).
  arm ∈ T / A-self / A-self×k / A-role / B-expert / B-solo — 순서는 과제별 무작위(seed 기록), 반복 r=1..k 마다 같은 순서.
  채점 = arm 의 terminate 뒤 score_hidden 1회, trigger=post_hoc. 루프 안에는 verify_visible 뿐.
비용 귀속 (F1-f): s0 생성비는 과제당 shared_s0_cost 로 한 번만 기록(run 수준 합계 shared_s0_cost_total). arm 의 cost_usd 는 그 arm 이 실제로 한
  호출만(B-solo 는 자기 호출뿐). 트레이스의 build 재생 행동은 NO_COST + flags=replayed_from_s0 + input_ref=s0 파일 (출처만 남긴다).
  보고는 "arm 단독 비용" 과 "실험 총지출 = Σarm + shared_s0" 을 구분한다.
예산 (§3): 계속 arm 의 추가 예산 b_cont (B-expert 1회 비용 중앙값, 파일럿 0회차 측정값을 인자로). B-solo 는 T(s0 비용) + b_cont.
  호출 직전 max_tokens = floor((잔여 − 입력 비용) / 출력 단가). < 256 이면 호출하지 않고 기존 산출물 제출, budget_refused=True (arm 수준, 계속 진행).
  전체 누적 상한은 D1 원장 — 예약 거부면 BudgetStop → 부분 결과 저장 후 종료 코드 2 (budget_stop, 실행 전체 중단). 둘은 다르다.
인프라 (F1-e): verify(가시·히든) 직후 infra=True 면 그 자리에서 InfraStop → 부분 결과 저장 → 중단, 후속 호출 0회.
출력 (F1-d): {"rows": [{task_id, arm, rep, hidden_pass, cost_usd, budget_refused, infra, …}], "shared_s0_cost": {task: $}, …} — scripts/gap_analysis.py 입력과 일치.
v2 스케줄러·공명·SOC 미사용. 얇은 루프. 히든 테스트는 프롬프트·루프 어디에도 없다.

    python -X utf8 -m benchmark.arms --pool bcb --ids evidence/week2/probe_ids_bcb.json --output evidence/week2/arms_pilot.json \\
        --b-cont 0.02 --a-call-median 0.003 --k 3 --seed 20260913
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from benchmark.agents_single import _DEFAULT_SYSTEM
from benchmark.features import ast_features, error_class
from benchmark.hidden_guard import hidden_pass_rate
from benchmark.features import FEATURES_VERSION
from benchmark.runloop import ArmBudget, CallAborted, InfraStop, _attempt_totals, budgeted_generate, input_tokens, require_budget, run_loop
from harmonet.budget import INPUT_MARGIN, Budget, BudgetStop, budget_from_env
from harmonet.llm import get_llm_client
from harmonet.pricing import price_for, sum_cost
from harmonet.trace import NO_COST, TaskState, model_used, verify_cost
from harmonet.usage import METER
from harmonet.verify import extract_artifact, score_hidden, verify_visible

ARMS = ("T", "A-self", "A-selfxk", "A-role", "B-expert", "B-solo")
MIN_MAX_TOKENS = 256
S0_FILES = ("artifact.py", "verify_visible.json", "prompt_context.json", "decision_signals.json")

REVIEWER_SYSTEM = (
    "You are a senior Python reviewer. You receive a task, a candidate solution, and the output of the visible checks. "
    "Find the defects and return the corrected, complete solution as a single fenced python code block. No prose outside the block."
)


def _revise_prompt(task_prompt: str, artifact: str, visible: Dict[str, Any]) -> str:
    return (f"### Task\n{task_prompt.strip()}\n\n### Current solution\n```python\n{artifact}\n```\n\n"
            f"### Visible check result\noutcome={visible['outcome']} level={visible['level']} n_run={visible['n_run']} "
            f"n_passed={visible['n_passed']} n_failed={visible['n_failed']}\n{visible['evidence'][-1500:]}\n\n"
            "Return the full corrected solution as one fenced python code block.")


def _max_tokens_for(model: Optional[str], remaining_usd: float, n_input_tokens: int) -> int:
    """§3 호출 규칙: floor((잔여 − 입력 비용) / 출력 단가). 입력 토큰은 count_tokens 실측 × 1.10 (F2 경로, chars/3 폐기 — J2)."""
    entry, sid = price_for(model)
    if entry is None:
        raise RuntimeError(f"[arms] 모델 {model!r} 가격이 {sid} 에 없다")
    input_usd = n_input_tokens * INPUT_MARGIN * entry["input"] / 1e6
    if entry["output"] <= 0:
        return 4096                                       # $0 모델(mock): 상한 규칙 적용 불가 → 기본값 (거부 없음)
    return int(math.floor((remaining_usd - input_usd) / (entry["output"] / 1e6)))


def _call(client, budget, prompt, system, remaining_usd, note, unknown_counter=None) -> Tuple[Optional[str], Dict[str, Any], Optional[float], int, list, str]:
    """max_tokens 규칙 → 예산 원장 예약 → 호출. (output|None, cost, usd, wall, max_tokens 목록(시도별), status).
    status ∈ {"ok", "refused", "refused_after_attempts", "aborted_unknown_cost"}. L1: 시도마다 arm 잔여로 max_tokens 재계산(ArmBudget); (c) 예약액은 arm 잔여에 즉시 반영.
    refused_after_attempts = 불명 시도 뒤 잔여 부족 — 출력 없음, usd 는 확정된 예약액. BudgetStop(전체 cap 등)은 시도 기록을 실은 채 위로 간다 (L5)."""
    n_in = input_tokens(client, prompt, system)
    model = getattr(client, "model", None)
    ab = ArmBudget(remaining_usd, lambda r: _max_tokens_for(model, r, n_in), MIN_MAX_TOKENS, int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096")))
    try:
        out, cost, usd, wall = budgeted_generate(client, budget, prompt, system, note=note, unknown_counter=unknown_counter, arm=ab)
    except CallAborted as e:
        tot = _attempt_totals(e.attempts)
        cost = {**NO_COST, "llm_calls": len(e.attempts), "attempts": e.attempts, "n_unknown_attempts": tot["n_unknown_attempts"],
                "unknown_reserved_usd": tot["unknown_reserved_usd"], "measured_usd": 0.0, "source": "measured" if e.attempts else "none"}
        mts = [x["max_tokens"] for x in e.attempts] + ([ab.max_tokens()] if e.reason == "arm_budget" else [])
        status = "aborted_unknown_cost" if e.reason == "unknown_cost_x2" else ("refused_after_attempts" if e.attempts else "refused")
        return None, cost, tot["unknown_reserved_usd"], 0, mts, status
    return out, cost, usd, wall, [x["max_tokens"] for x in cost["attempts"]], "ok"


def _check_infra(result: Dict[str, Any], where: str) -> None:
    if result.get("infra"):
        raise InfraStop(f"{where}: 채점 인프라 장애 — {result.get('evidence', '')[-200:]}")


def _safe(name: str) -> str:
    return name.replace("/", "_")


def _s0_hash(d: Path) -> str:
    """s0 스냅샷 해시 = 후보 + 가시 검증 결과 + 결정 신호 + 설정(prompt_context: 프롬프트·모델·시스템 프롬프트·spec) 전부 (J2: 앞의 둘만 있던 것을 확장)."""
    h = hashlib.sha256()
    for n in S0_FILES:
        h.update(n.encode()); h.update((d / n).read_bytes())
    return h.hexdigest()


def config_hash(clients: Dict[str, Any], cfg: Dict[str, Any], pool: str) -> str:
    """result.json 재사용 키 (J2): 모델 A/B·온도·max_tokens 상한·arm 설정(b_cont 등)·채점기 버전·특징 추출기 버전·풀. 불일치 → 재실행."""
    from benchmark.bcb_eligibility import checker_version   # 호스트에는 bigcodebench 가 없어 텍스트에서 읽는다
    from harmonet.verify import BCB_IMAGE_DEFAULT
    key = {"model_a": getattr(clients["A"], "model", None), "model_b": getattr(clients["B"], "model", None),
           "temperature": os.getenv("ANTHROPIC_TEMPERATURE"), "max_tokens_cap": os.getenv("ANTHROPIC_MAX_TOKENS", "4096"),
           "cfg": {k: v for k, v in cfg.items() if k not in ("k", "config_hash")}, "pool": pool, "checker": checker_version(), "bcb_image": os.getenv("HARMONET_BCB_IMAGE", BCB_IMAGE_DEFAULT),
           "features": FEATURES_VERSION}
    return hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ── s0 스냅샷 ────────────────────────────────────────────────────────────
def make_s0(task_id: str, task_prompt: str, spec_visible: Dict[str, Any], client_a, budget: Optional[Budget], root: Path) -> Tuple[Path, bool]:
    """(s0 dir, created). 이미 있으면 sha256 대조 후 재사용 — 덮어쓰지 않는다."""
    d = root / _safe(task_id) / "s0"
    if (d / "sha256.txt").exists():
        if not all((d / n).exists() for n in S0_FILES):
            raise RuntimeError(f"[arms] s0 불완전: {d}")
        if (d / "sha256.txt").read_text(encoding="utf-8").strip() != _s0_hash(d):
            raise RuntimeError(f"[arms] s0 해시 불일치 — 스냅샷이 바뀌었다: {d}")
        return d, False
    if d.exists() and any(d.iterdir()):
        raise RuntimeError(f"[arms] s0 디렉터리가 있으나 sha256.txt 가 없다 (부분 생성?) — 수동 확인 필요: {d}")
    d.mkdir(parents=True, exist_ok=True)
    out, cost, usd, wall = budgeted_generate(client_a, budget, task_prompt, _DEFAULT_SYSTEM, note=f"{task_id} s0")
    report: Dict[str, str] = {}
    artifact = extract_artifact(out, "code", report=report)
    visible = verify_visible(artifact, spec_visible)
    model_a = model_used(client_a.role, client_a)
    (d / "artifact.py").write_text(artifact + "\n", encoding="utf-8")
    (d / "verify_visible.json").write_text(json.dumps(visible, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "prompt_context.json").write_text(json.dumps({"task_id": task_id, "task_prompt": task_prompt, "spec_visible": spec_visible,
                                                       "system_prompt": _DEFAULT_SYSTEM, "model_a": model_a, "extraction": report.get("extraction"),
                                                       "raw_output_head": out[:200], "build_cost": cost, "build_cost_usd": usd, "wall_ms": wall},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    signals = {  # §8: 기록만, 2주차에는 분석하지 않는다
        "outcome": visible["outcome"], "level": visible["level"], "n_run": visible["n_run"], "n_passed": visible["n_passed"],
        "n_failed": visible["n_failed"], "flags": visible["flags"], "applied": visible["applied"], "infra": visible.get("infra", False),
        "error_kinds": sorted(set(w for w in ("SyntaxError", "AssertionError", "TypeError", "NameError", "ImportError", "timeout", "aborted")
                                  if w in visible["evidence"])),
        "artifact_chars": len(artifact), "artifact_lines": artifact.count("\n") + 1, "diag_tail": visible["evidence"][-300:],
        "build_tokens": {k: cost[k] for k in ("prompt_tokens", "completion_tokens")}, "build_cost_usd": usd, "build_wall_ms": wall,
        "prompt_chars": len(task_prompt), "budget_refused": False,
        **{k: v for k, v in ast_features(artifact).items() if k != "ast_ok"}, "error_class": error_class(visible["evidence"][-300:]),   # I1 post 특징
    }
    (d / "decision_signals.json").write_text(json.dumps(signals, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "sha256.txt").write_text(_s0_hash(d), encoding="utf-8")
    _check_infra(visible, f"{task_id} s0 verify_visible")   # 스냅샷은 남기고(재사용 가능) 실행은 여기서 멈춘다
    return d, True


def task_id_of(s0_dir: Path) -> str:
    return json.loads((s0_dir / "prompt_context.json").read_text(encoding="utf-8"))["task_id"]


def load_s0(d: Path) -> Dict[str, Any]:
    return {"artifact": (d / "artifact.py").read_text(encoding="utf-8").rstrip("\n"),
            "visible": json.loads((d / "verify_visible.json").read_text(encoding="utf-8")),
            "ctx": json.loads((d / "prompt_context.json").read_text(encoding="utf-8")),
            "files": [str(d / n) for n in S0_FILES]}


# ── arm 실행 ─────────────────────────────────────────────────────────────
def run_arm(arm: str, rep: int, s0_dir: Path, spec_full: Dict[str, Any], clients: Dict[str, Any], cfg: Dict[str, Any],
            budget: Optional[Budget], run_id: str, unknown_counter: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    arm_dir = s0_dir.parent / _safe(arm) / f"rep{rep}"
    done = arm_dir / "result.json"
    if done.exists():                                       # 멱등: 같은 config_hash 로 끝난 (arm, rep) 만 건너뛴다 (J2). 다르면 재실행(덮어씀)
        prev = json.loads(done.read_text(encoding="utf-8"))
        if prev.get("config_hash") == cfg["config_hash"]:
            return prev
        print(f"[arms] {task_id_of(s0_dir)} {arm} rep{rep}: config_hash 불일치 ({str(prev.get('config_hash'))[:8]} != {cfg['config_hash'][:8]}) → 재실행", flush=True)
    s0 = load_s0(s0_dir)                                   # 디스크에서 재개 — 메모리 상태 재사용 금지
    task_id, ctx = s0["ctx"]["task_id"], s0["ctx"]
    spec_visible = ctx["spec_visible"]
    state = TaskState(task_id, system=arm)
    # s0 의 build 를 출처로만 재생: 비용 0 (s0 비용은 run 수준 shared_s0_cost 로 한 번만 계상, F1-f)
    state.record("build", "builder", ctx["model_a"], NO_COST, ctx["raw_output_head"], input_ref=s0["files"][2:3],
                 output_ref=s0["files"][0:1], flags=["replayed_from_s0", "cost_in_shared_s0"])
    state.record("verify", "validator", "none", verify_cost(s0["visible"]), s0["visible"]["evidence"][:400], input_ref=s0["files"][1:2],
                 flags=["replayed_from_s0"])
    artifact, visible = s0["artifact"], s0["visible"]
    arm_dir.mkdir(parents=True, exist_ok=True)
    b_cont = float(cfg["b_cont"])
    remaining = b_cont + ((ctx["build_cost_usd"] or 0.0) if arm == "B-solo" else 0.0)
    spent, n_calls, refused, calls_max_tokens, n_attempts, n_unknown, aborted = 0.0, 0, False, [], 0, 0, False
    measured_spent, unknown_spent, attempt_log = 0.0, 0.0, []                     # L1-7: 실측 / 보수적 귀속 분리, L5: 시도 기록
    unknown_counter = unknown_counter if unknown_counter is not None else {"n": 0}

    def _book(cost, usd):
        nonlocal spent, remaining, n_attempts, n_unknown, measured_spent, unknown_spent
        n_attempts += int(cost.get("llm_calls", 0)); n_unknown += int(cost.get("n_unknown_attempts", 0))   # 모든 시도를 arm 호출 수·비용에 반영 (K2)
        m = cost.get("measured_usd")
        measured_spent = None if (m is None and cost.get("llm_calls", 0)) or measured_spent is None else measured_spent + (m or 0.0)   # M3: None 은 0 이 아니다
        unknown_spent += cost.get("unknown_reserved_usd") or 0.0
        spent = None if (usd is None or spent is None) else spent + usd
        remaining -= usd or 0.0
        attempt_log.extend(cost.get("attempts", []))

    def step(kind: str, client, prompt: str, system: str, trigger: str, note: str) -> bool:
        nonlocal artifact, visible, n_calls, refused, aborted
        try:
            out, cost, usd, wall, mts, status = _call(client, budget, prompt, system, remaining, note, unknown_counter)
        except BudgetStop as e:                           # L5/M3: 성공 없이 끝난 시도(또는 성공 확정 뒤 cap 초과)도 arm 장부에 남긴 뒤 위로 — 같은 집계 함수
            _book({**_attempt_totals(e.attempts), "llm_calls": len(e.attempts), "attempts": e.attempts}, e.usd)
            raise
        calls_max_tokens.extend(mts)
        _book(cost, usd)
        if status in ("refused", "refused_after_attempts"):   # L1-4: 최소 출력 예산 미달 → 추가 호출 없이 기존 종료 규칙
            refused = True
            state.record(kind, client.role, model_used(client.role, client), cost if status == "refused_after_attempts" else NO_COST,
                         f"budget_refused({status}): max_tokens={mts[-1] if mts else '?'} < {MIN_MAX_TOKENS}, attempts={len(cost.get('attempts', []))}",
                         trigger=trigger, flags=["budget_refused", status])
            return False
        if status == "aborted_unknown_cost":              # (c) 2회: 이 arm 은 더 호출하지 않고 기존 산출물로 종료
            aborted = True
            state.record(kind, client.role, model_used(client.role, client), cost, f"aborted_unknown_cost: {cost['attempts']}", trigger=trigger,
                         flags=["aborted_unknown_cost"])
            return False
        n_calls += 1
        mt = mts[-1]
        report: Dict[str, str] = {}
        new_artifact = extract_artifact(out, "code", report=report)
        p = arm_dir / f"artifact_{n_calls}.py"
        p.write_text(new_artifact + "\n", encoding="utf-8")
        state.record(kind, client.role, model_used(client.role, client), cost, out[:200], trigger=trigger, output_ref=[str(p)],
                     flags=[f"extraction={report.get('extraction')}", f"max_tokens={mt}"])
        artifact = new_artifact
        visible = verify_visible(artifact, spec_visible)
        vp = arm_dir / f"verify_visible_{n_calls}.json"
        vp.write_text(json.dumps(visible, ensure_ascii=False, indent=1), encoding="utf-8")
        state.record("verify", "validator", "none", verify_cost(visible), visible["evidence"][:400], output_ref=[str(vp)])
        _check_infra(visible, f"{task_id} {arm} rep{rep} verify_visible")
        return True

    A, B = clients["A"], clients["B"]
    try:
        if arm == "T":
            pass
        elif arm == "A-self":
            step("self_revise", A, _revise_prompt(ctx["task_prompt"], artifact, visible), _DEFAULT_SYSTEM, "verify:visible", f"{task_id} A-self r{rep}")
        elif arm == "A-selfxk":
            k = int(math.floor(b_cont / float(cfg["a_call_median"]))) if float(cfg["a_call_median"]) > 0 else 1
            k = max(1, min(k, int(cfg.get("k_max", 8))))
            for i in range(k):
                if cfg.get("stop_on_visible_pass", True) and visible["passed"]:
                    break
                if not step("self_revise", A, _revise_prompt(ctx["task_prompt"], artifact, visible), _DEFAULT_SYSTEM, "verify:visible",
                            f"{task_id} A-selfxk r{rep} {i + 1}/{k}"):
                    break
        elif arm == "A-role":
            step("expert_review", A, _revise_prompt(ctx["task_prompt"], artifact, visible), REVIEWER_SYSTEM, "verify:visible", f"{task_id} A-role r{rep}")
        elif arm == "B-expert":
            step("expert_review", B, _revise_prompt(ctx["task_prompt"], artifact, visible), REVIEWER_SYSTEM, "verify:visible", f"{task_id} B-expert r{rep}")
        elif arm == "B-solo":
            artifact, visible = "", {"outcome": "none"}
            step("build", B, ctx["task_prompt"], _DEFAULT_SYSTEM, "none", f"{task_id} B-solo r{rep}")
            if refused:
                artifact, visible = s0["artifact"], s0["visible"]   # 규칙: 호출 못 하면 기존(s0) 산출물 제출
        else:
            raise ValueError(arm)
    except BudgetStop as e:                               # L5: 미완료 arm — 완료 행과 구분해 기록, result.json 은 쓰지 않는다(재개 시 재실행)
        inc = {"task_id": task_id, "arm": arm, "rep": rep, "incomplete": True, "stop_reason": e.reason, "n_calls_done": n_calls, "n_attempts": n_attempts,
               "n_unknown_attempts": n_unknown, "measured_usd": None if measured_spent is None else round(measured_spent, 10),
               "unknown_reserved_usd": round(unknown_spent, 10), "cost_usd": None if spent is None else round(spent, 10),
               "attempts": attempt_log, "max_tokens": calls_max_tokens, "b_cont": b_cont, "config_hash": cfg["config_hash"],
               "s0_dir": str(s0_dir), "t": time.time()}
        inc_path = arm_dir / f"incomplete_{int(inc['t'] * 1000)}.json"
        inc_path.write_text(json.dumps(inc, ensure_ascii=False, indent=1), encoding="utf-8")
        inc["path"] = str(inc_path)
        e.incomplete = inc
        raise
    state.artifact = artifact
    state.verification = visible
    state.record("terminate", arm, "none", NO_COST, f"{arm} rep{rep}: n_calls={n_calls} attempts={n_attempts} unknown={n_unknown} refused={refused} aborted={aborted} "
                 f"spent={spent} (measured {measured_spent} + unknown_reserved {unknown_spent:.5f})")
    hidden = score_hidden(artifact, spec_full)              # 종료 후에만
    state.set_score(hidden)
    trace_path = state.save(f"{run_id}/rep{rep}")
    _check_infra(hidden, f"{task_id} {arm} rep{rep} score_hidden")
    row = {"task_id": task_id, "arm": arm, "rep": rep, "hidden_pass": bool(hidden["passed"]), "passed": bool(hidden["passed"]),
           "outcome": hidden["outcome"], "hidden_level": hidden["level"], "hidden_sandbox": hidden["sandbox"], "hidden_exec_count": hidden["exec_count"],
           "visible_outcome": visible["outcome"], "n_calls": n_calls, "n_attempts": n_attempts, "n_unknown_attempts": n_unknown, "aborted_unknown_cost": aborted,
           "budget_refused": refused, "max_tokens": calls_max_tokens,
           "cost_usd": state.cost_so_far["cost_usd"], "cost_measured_usd": None if measured_spent is None else round(measured_spent, 10),
           "cost_unknown_reserved_usd": round(unknown_spent, 10),
           "attempts": attempt_log, "b_cont": b_cont,
           "models": sorted({a.model for a in state.history if a.model != "none" and "replayed_from_s0" not in a.flags}),
           "infra": bool(hidden.get("infra") or visible.get("infra")), "hidden_exposed": spec_full.get("hidden_exposed"),
           "trace_path": str(trace_path), "s0_dir": str(s0_dir), "config_hash": cfg["config_hash"]}
    done.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return row


def run_task_all_arms(task_id: str, task_prompt: str, spec_full: Dict[str, Any], clients, cfg, budget, root: Path, run_id: str, seed: int,
                      k: int, arms: Sequence[str] = ARMS) -> Dict[str, Any]:
    spec_visible = {kk: v for kk, v in spec_full.items() if kk != "hidden_tests"}
    try:
        s0_dir, created = make_s0(task_id, task_prompt, spec_visible, clients["A"], budget, root)
    except BudgetStop as e:                                 # L5: s0 생성 중 중단 — arm 이 아니어도 시도 기록·비용 보존 (s0/incomplete_*.json)
        inc0 = None
        if getattr(e, "attempts", None):
            tot = _attempt_totals(e.attempts)
            d = root / _safe(task_id) / "s0"; d.mkdir(parents=True, exist_ok=True)
            inc0 = {"task_id": task_id, "arm": "s0", "rep": 0, "incomplete": True, "stop_reason": e.reason, "n_calls_done": 0, "n_attempts": len(e.attempts),
                    "n_unknown_attempts": tot["n_unknown_attempts"], "measured_usd": tot["measured_usd"], "unknown_reserved_usd": tot["unknown_reserved_usd"],
                    "cost_usd": tot["cost_usd"], "attempts": e.attempts, "max_tokens": [a.get("max_tokens") for a in e.attempts], "t": time.time()}
            p0 = d / f"incomplete_{int(inc0['t'] * 1000)}.json"; p0.write_text(json.dumps(inc0, ensure_ascii=False, indent=1), encoding="utf-8")
            inc0["path"] = str(p0); e.incomplete = inc0
        e.partial = {"task_id": task_id, "order": [], "rows": [], "incomplete_arms": [inc0] if inc0 else [], "shared_s0_cost": 0.0, "s0_created": False,
                     "cost_usd": 0.0, "infra": False, "line": f"BUDGET STOP ({e.reason}) at s0"}
        raise
    ctx = json.loads((s0_dir / "prompt_context.json").read_text(encoding="utf-8"))
    order = list(ARMS)
    random.Random(f"{seed}:{task_id}").shuffle(order)      # 과제별 무작위, 반복마다 같은 순서, seed 기록
    order = [a for a in order if a in arms]                # --arms 부분집합 (뒤집힘 부분집합 등), 순서는 전체 순열에서 유지
    (s0_dir.parent / "arm_order.json").write_text(json.dumps({"seed": seed, "order": order, "k": k}), encoding="utf-8")
    rows: List[Dict[str, Any]] = []
    unknown_counter = {"n": 0}                              # K2 (c) 과제 수준 카운터 — 2회면 그 arm 중단
    try:
        for rep in range(1, k + 1):
            for arm in order:
                rows.append(run_arm(arm, rep, s0_dir, spec_full, clients, cfg, budget, run_id, unknown_counter))
    except InfraStop as e:                                  # 부분 결과를 실어 위로 (저장 후 중단)
        e.partial = {"task_id": task_id, "order": order, "rows": rows, "shared_s0_cost": ctx["build_cost_usd"], "s0_created": created, "s0_dir": str(s0_dir),
                     "cost_usd": sum_cost(rows)["cost_usd"] if rows else 0.0, "infra": True, "line": "INFRA STOP"}
        raise
    except BudgetStop as e:                                 # J2/L5: 완료 arm 행 + 미완료 arm 의 시도 기록을 부분 결과에 (원장에는 이미 있는 비용)
        inc = [e.incomplete] if getattr(e, "incomplete", None) else []
        e.partial = {"task_id": task_id, "order": order, "rows": rows, "incomplete_arms": inc, "shared_s0_cost": ctx["build_cost_usd"], "s0_created": created, "s0_dir": str(s0_dir),
                     "cost_usd": sum_cost(rows)["cost_usd"] if rows else 0.0, "infra": False,
                     "line": f"BUDGET STOP ({e.reason}) after {len(rows)} arm rows, incomplete {[i['arm'] for i in inc]}"}
        raise
    return {"task_id": task_id, "order": order, "rows": rows, "shared_s0_cost": ctx["build_cost_usd"], "s0_created": created, "s0_dir": str(s0_dir),
            "cost_usd": sum_cost(rows)["cost_usd"], "infra": any(r["infra"] for r in rows),
            "line": " ".join(f"{r['arm']}r{r['rep']}={'P' if r['hidden_pass'] else r['outcome'][:1]}" for r in rows)}


def _sum_or_none(vals) -> Optional[float]:
    """None(실측 미상)이 하나라도 있으면 합계도 None — 조용히 0 으로 바꾸지 않는다 (M3)."""
    vals = list(vals)
    return None if any(v is None for v in vals) else round(sum(vals), 10)


def incomplete_episodes(root: Path) -> List[Dict[str, Any]]:
    """run 루트 아래 모든 incomplete_*.json (미완료 arm 에피소드). 완료 행(result.json)과 구분되며 분석 입력이 아니다 — 원장 대조용 (L5)."""
    out = []
    for p in sorted(list(root.glob("*/*/rep*/incomplete_*.json")) + list(root.glob("*/s0/incomplete_*.json"))):
        d = json.loads(p.read_text(encoding="utf-8")); d["path"] = str(p)
        out.append(d)
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for arm in ARMS:
        a = [r for r in rows if r["arm"] == arm]
        if a:
            out[arm] = {"n": len(a), "hidden_pass": hidden_pass_rate(a, arm), "refused_rate": sum(r["budget_refused"] for r in a) / len(a),
                        **{"cost_own_" + kk: v for kk, v in sum_cost(a).items()},
                        "cost_measured_usd": _sum_or_none(r.get("cost_measured_usd", 0.0) for r in a), "cost_unknown_reserved_usd": _sum_or_none(r.get("cost_unknown_reserved_usd", 0.0) for r in a),
                        "n_calls_mean": sum(r["n_calls"] for r in a) / len(a), "n_attempts_mean": sum(r.get("n_attempts", r["n_calls"]) for r in a) / len(a),
                        "models": sorted({m for r in a for m in r["models"]})}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", choices=["bcb", "mbppplus"], required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--b-cont", type=float, required=True, help="계속 arm 추가 예산 USD (파일럿 0회차 B-expert 1회 비용 중앙값)")
    ap.add_argument("--a-call-median", type=float, required=True, help="A 1회 호출 비용 중앙값 USD (k 계산용)")
    ap.add_argument("--k", type=int, default=1, help="arm 반복 수 (같은 s0 에서)")
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--k-max", type=int, default=8)
    ap.add_argument("--arms", default=",".join(ARMS), help="실행할 arm 부분집합 (쉼표). 기본 6개 전부")
    args = ap.parse_args()
    arms_sel = tuple(a for a in args.arms.split(",") if a)
    if any(a not in ARMS for a in arms_sel):
        raise SystemExit(f"[arms] 알 수 없는 arm: {arms_sel}")
    ids = json.loads(Path(args.ids).read_text(encoding="utf-8"))["ids"]
    if args.pool == "bcb":
        from benchmark.bcb import load_bcb
        tasks = {t.task_id: (t.prompt, t.spec(visible=True)) for t in load_bcb(ids)}
    else:
        from benchmark.mbppplus import load_mbppplus
        tasks = {t.task_id: (t.prompt, t.spec()) for t in load_mbppplus(ids)}
    missing = [i for i in ids if i not in tasks]
    if missing:
        raise SystemExit(f"[arms] 없는 id: {missing[:5]}")
    run_id = os.getenv("HARMONET_TRACE_RUN_ID") or f"arms_{time.strftime('%Y%m%d_%H%M%S')}"
    budget = budget_from_env(run_id)
    require_budget(budget)
    clients = {"A": get_llm_client("builder"), "B": get_llm_client("reviewer")}
    if clients["A"].model == clients["B"].model:
        raise RuntimeError("[arms] A 와 B 가 같은 모델 — B-expert / B-solo 가 A 와 구별되지 않는다 (HARMONET_MODEL_BUILDER / _REVIEWER)")
    if args.pool == "bcb":
        from benchmark.bcb import bcb_preflight
        print("[preflight]", bcb_preflight(), flush=True)
    cfg = {"b_cont": args.b_cont, "a_call_median": args.a_call_median, "k_max": args.k_max, "stop_on_visible_pass": True,
           "min_max_tokens": MIN_MAX_TOKENS, "k": args.k}
    cfg["config_hash"] = config_hash(clients, cfg, args.pool)   # k 는 키에 안 넣는다: 뒤집힘 부분집합(k=2)이 주 실행(k=1)의 rep1 을 재사용해야 한다
    root = Path(os.getenv("HARMONET_ARMS_ROOT") or (Path(__file__).resolve().parent.parent / "evidence" / "week2")) / run_id
    out = Path(args.output)

    def _write(task_rows, stopped):
        flat = [r for t in task_rows for r in t["rows"]]
        shared = {t["task_id"]: t["shared_s0_cost"] for t in task_rows}
        shared_total = None if any(v is None for v in shared.values()) else round(sum(shared.values()), 8)
        own = sum_cost(flat)
        incomplete = incomplete_episodes(root)                # L5: 이 실행 + 이전 실행(재개)의 미완료 arm 에피소드 전부 — 파일 하나 = 에피소드 하나 (이중 계상 없음)
        inc_usd = _sum_or_none(i["cost_usd"] for i in incomplete)
        total = None if (own["cost_usd"] is None or shared_total is None or inc_usd is None) else round(own["cost_usd"] + shared_total + inc_usd, 8)
        out.write_text(json.dumps({"run_id": run_id, "config": cfg, "seed": args.seed, "pool": args.pool, "ids_file": args.ids,
                                   "stopped_reason": stopped, "summary": summarize(flat) if flat else {},
                                   "cost": {"arms_own_usd": own["cost_usd"], "n_unpriced": own["n_unpriced"], "shared_s0_cost_total": shared_total,
                                            "incomplete_usd": inc_usd, "n_incomplete": len(incomplete),
                                            "measured_usd": _sum_or_none([r.get("cost_measured_usd", 0.0) for r in flat] + [i["measured_usd"] for i in incomplete]),
                                            "unknown_reserved_usd": _sum_or_none([r.get("cost_unknown_reserved_usd", 0.0) for r in flat] + [i["unknown_reserved_usd"] for i in incomplete]),
                                            "total_spent_usd": total},
                                   "shared_s0_cost": shared, "s0_dirs": {t["task_id"]: t.get("s0_dir") for t in task_rows},
                                   "task_order": {t["task_id"]: t["order"] for t in task_rows}, "rows": flat, "incomplete_arms": incomplete},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["task_id", "arm", "rep", "hidden_pass", "outcome", "visible_outcome", "n_calls", "budget_refused",
                                              "cost_usd", "models", "infra", "trace_path"], extrasaction="ignore")
            w.writeheader()
            w.writerows([{**r, "models": ",".join(r["models"])} for r in flat])

    run_loop(ids, lambda tid: run_task_all_arms(tid, tasks[tid][0], tasks[tid][1], clients, cfg, budget, root, run_id, args.seed, args.k, arms_sel),
             _write, budget, label="arms")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
