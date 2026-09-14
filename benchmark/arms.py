"""
benchmark/arms.py — 6 arm 실행기 (Week2-D5, 풀 무관 인프라). 설계: docs/week2_design_draft.md §2·§3·§6·§7·§8.

과제마다:
  s0  = A(builder) 1회 build → verify_visible → 디스크 스냅샷 evidence/week2/<run_id>/<task>/s0/
        {artifact.py, verify_visible.json, prompt_context.json, decision_signals.json}
  arm ∈ T / A-self / A-self×k / A-role / B-expert / B-solo — 순서는 과제별 무작위(seed 기록). 모든 계속 arm 은 **디스크의 s0 를 읽어** 재개한다
        (메모리 상태 재사용 금지). arm 마다 TaskState 하나: build 행동은 s0 기록에서 재생(input_ref = s0 파일), 계속 행동은 새로 기록.
  채점 = 각 arm 의 에피소드 종료(terminate) 뒤 score_hidden 1회, trigger=post_hoc. 루프 안에는 verify_visible 뿐.

예산 (§3): 계속 arm 의 추가 예산 b_cont (B-expert 1회 비용 중앙값, 파일럿 0회차에서 측정해 인자로 준다). B-solo 는 T(s0 비용) + b_cont.
  호출 직전 max_tokens = floor((잔여 − 입력 비용) / 출력 단가). < 256 이면 호출하지 않고 기존 산출물 제출, budget_refused=True (arm 수준, 계속 진행).
  A-self×k: k = floor(b_cont / A 1회 비용 중앙값), 가시 검증이 pass 면 조기 종료(stop_on_visible_pass, 설정에 기록).
  전체 누적 상한은 D1 원장(HARMONET_BUDGET_CAP) — 예약 거부면 BudgetStop → 부분 결과 저장 후 종료 코드 2 (budget_stop, 실행 전체 중단).
  둘은 다르다: budget_refused = 이 arm 의 개별 예산 규칙, budget_stop = 사전 등록된 총액 상한.

v2 스케줄러·공명·SOC 미사용. 얇은 루프. 히든 테스트는 프롬프트·루프 어디에도 없다.

    python -X utf8 -m benchmark.arms --pool bcb --ids evidence/week2/probe_ids_bcb.json --output evidence/week2/arms_pilot.json \\
        --b-cont 0.02 --a-call-median 0.003 --seed 20260913
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from benchmark.agents_single import _DEFAULT_SYSTEM
from benchmark.hidden_guard import hidden_pass_rate
from benchmark.runloop import budgeted_generate, require_budget, run_loop
from harmonet.budget import Budget, budget_from_env
from harmonet.llm import get_llm_client
from harmonet.pricing import price_for, sum_cost
from harmonet.trace import NO_COST, TaskState, model_used, verify_cost
from harmonet.usage import METER
from harmonet.verify import extract_artifact, score_hidden, verify_visible

ARMS = ("T", "A-self", "A-selfxk", "A-role", "B-expert", "B-solo")
MIN_MAX_TOKENS = 256

REVIEWER_SYSTEM = (
    "You are a senior Python reviewer. You receive a task, a candidate solution, and the output of the visible checks. "
    "Find the defects and return the corrected, complete solution as a single fenced python code block. No prose outside the block."
)


def _revise_prompt(task_prompt: str, artifact: str, visible: Dict[str, Any]) -> str:
    return (f"### Task\n{task_prompt.strip()}\n\n### Current solution\n```python\n{artifact}\n```\n\n"
            f"### Visible check result\noutcome={visible['outcome']} level={visible['level']} n_run={visible['n_run']} "
            f"n_passed={visible['n_passed']} n_failed={visible['n_failed']}\n{visible['evidence'][-1500:]}\n\n"
            "Return the full corrected solution as one fenced python code block.")


def _max_tokens_for(model: Optional[str], remaining_usd: float, prompt_chars: int) -> int:
    """§3 호출 규칙: floor((잔여 − 입력 비용) / 출력 단가). 입력 토큰은 chars/3 (보수적)."""
    entry, sid = price_for(model)
    if entry is None:
        raise RuntimeError(f"[arms] 모델 {model!r} 가격이 {sid} 에 없다")
    input_usd = prompt_chars / 3.0 * entry["input"] / 1e6
    if entry["output"] <= 0:
        return 4096                                       # mock ($0): 상한 규칙 적용 불가 → 기본값 (거부 없음)
    return int(math.floor((remaining_usd - input_usd) / (entry["output"] / 1e6)))


def _call(client, budget, prompt, system, remaining_usd, note) -> Tuple[Optional[str], Dict[str, Any], Optional[float], int, int, bool]:
    """max_tokens 규칙 → 예산 원장 예약 → 호출. (output|None, cost, usd, wall, max_tokens, refused)."""
    mt = _max_tokens_for(getattr(client, "model", None), remaining_usd, len(prompt) + len(system))
    if mt < MIN_MAX_TOKENS:
        return None, dict(NO_COST), 0.0, 0, mt, True
    mt = min(mt, int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096")))
    old = getattr(client, "max_tokens", None)
    client.max_tokens = mt
    try:
        out, cost, usd, wall = budgeted_generate(client, budget, prompt, system, note=note)
    finally:
        if old is not None:
            client.max_tokens = old
    return out, cost, usd, wall, mt, False


# ── s0 스냅샷 ────────────────────────────────────────────────────────────
def make_s0(task_id: str, task_prompt: str, spec_visible: Dict[str, Any], client_a, budget: Optional[Budget], root: Path) -> Path:
    d = root / _safe(task_id) / "s0"
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
    }
    (d / "decision_signals.json").write_text(json.dumps(signals, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def load_s0(d: Path) -> Dict[str, Any]:
    return {"artifact": (d / "artifact.py").read_text(encoding="utf-8").rstrip("\n"),
            "visible": json.loads((d / "verify_visible.json").read_text(encoding="utf-8")),
            "ctx": json.loads((d / "prompt_context.json").read_text(encoding="utf-8")),
            "files": [str(d / n) for n in ("artifact.py", "verify_visible.json", "prompt_context.json", "decision_signals.json")]}


def _safe(name: str) -> str:
    return name.replace("/", "_")


# ── arm 실행 ─────────────────────────────────────────────────────────────
def run_arm(arm: str, s0_dir: Path, spec_full: Dict[str, Any], clients: Dict[str, Any], cfg: Dict[str, Any], budget: Optional[Budget],
            run_id: str) -> Dict[str, Any]:
    s0 = load_s0(s0_dir)                                   # 디스크에서 재개 — 메모리 상태 재사용 금지
    task_id, ctx = s0["ctx"]["task_id"], s0["ctx"]
    spec_visible = ctx["spec_visible"]
    state = TaskState(task_id, system=arm)
    # s0 의 build 행동을 재생 (비용은 s0 기록값; 이 arm 이 새로 지불한 것이 아님을 flags 로)
    state.record("build", "builder", ctx["model_a"], ctx["build_cost"], ctx["raw_output_head"], input_ref=s0["files"][2:3],
                 output_ref=s0["files"][0:1], flags=["replayed_from_s0"])
    state.record("verify", "validator", "none", verify_cost(s0["visible"]), s0["visible"]["evidence"][:400], input_ref=s0["files"][1:2])
    artifact, visible = s0["artifact"], s0["visible"]
    arm_dir = s0_dir.parent / _safe(arm)
    arm_dir.mkdir(parents=True, exist_ok=True)
    b_cont = float(cfg["b_cont"])
    remaining = b_cont + (ctx["build_cost_usd"] or 0.0 if arm == "B-solo" else 0.0)
    spent, n_calls, refused, calls_max_tokens = 0.0, 0, False, []

    def step(kind: str, client, prompt: str, system: str, trigger: str, note: str) -> bool:
        nonlocal artifact, visible, remaining, spent, n_calls, refused
        out, cost, usd, wall, mt, was_refused = _call(client, budget, prompt, system, remaining, note)
        calls_max_tokens.append(mt)
        if was_refused:
            refused = True
            state.record(kind, client.role, model_used(client.role, client), NO_COST, f"budget_refused: max_tokens={mt} < {MIN_MAX_TOKENS}",
                         trigger=trigger, flags=["budget_refused"])
            return False
        n_calls += 1
        spent += usd or 0.0
        remaining -= usd or 0.0
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
        return True

    A, B = clients["A"], clients["B"]
    if arm == "T":
        pass
    elif arm == "A-self":
        step("self_revise", A, _revise_prompt(ctx["task_prompt"], artifact, visible), _DEFAULT_SYSTEM, "verify:visible", f"{task_id} A-self")
    elif arm == "A-selfxk":
        k = int(math.floor(b_cont / float(cfg["a_call_median"]))) if float(cfg["a_call_median"]) > 0 else 1
        k = max(1, min(k, int(cfg.get("k_max", 8))))
        for i in range(k):
            if cfg.get("stop_on_visible_pass", True) and visible["passed"]:
                break
            if not step("self_revise", A, _revise_prompt(ctx["task_prompt"], artifact, visible), _DEFAULT_SYSTEM, "verify:visible", f"{task_id} A-selfxk {i + 1}/{k}"):
                break
    elif arm == "A-role":
        step("expert_review", A, _revise_prompt(ctx["task_prompt"], artifact, visible), REVIEWER_SYSTEM, "verify:visible", f"{task_id} A-role")
    elif arm == "B-expert":
        step("expert_review", B, _revise_prompt(ctx["task_prompt"], artifact, visible), REVIEWER_SYSTEM, "verify:visible", f"{task_id} B-expert")
    elif arm == "B-solo":
        artifact, visible = "", {"outcome": "none"}
        step("build", B, ctx["task_prompt"], _DEFAULT_SYSTEM, "none", f"{task_id} B-solo")
        if refused:
            artifact, visible = s0["artifact"], s0["visible"]   # 규칙: 호출 못 하면 기존(s0) 산출물 제출
    else:
        raise ValueError(arm)
    state.artifact = artifact
    state.verification = visible
    state.record("terminate", arm, "none", NO_COST, f"{arm}: n_calls={n_calls} refused={refused} spent=${spent:.5f}")
    hidden = score_hidden(artifact, spec_full)              # 종료 후에만
    state.set_score(hidden)
    trace_path = state.save(run_id)
    return {"task_id": task_id, "arm": arm, "passed": hidden["passed"], "outcome": hidden["outcome"], "visible_outcome": visible["outcome"],
            "n_calls": n_calls, "budget_refused": refused, "max_tokens": calls_max_tokens, "cost_cont_usd": round(spent, 8),
            "cost_usd": state.cost_so_far["cost_usd"], "b_cont": b_cont, "models": sorted({a.model for a in state.history if a.model != "none"}),
            "infra": bool(hidden.get("infra") or visible.get("infra")), "hidden_exposed": spec_full.get("hidden_exposed"),
            "trace_path": str(trace_path), "s0_dir": str(s0_dir)}


def run_task_all_arms(task_id: str, task_prompt: str, spec_full: Dict[str, Any], clients, cfg, budget, root: Path, run_id: str, seed: int
                      ) -> Dict[str, Any]:
    spec_visible = {k: v for k, v in spec_full.items() if k != "hidden_tests"}
    s0_dir = make_s0(task_id, task_prompt, spec_visible, clients["A"], budget, root)
    order = list(ARMS)
    random.Random(f"{seed}:{task_id}").shuffle(order)      # 과제별 무작위, seed 기록
    rows = [run_arm(arm, s0_dir, spec_full, clients, cfg, budget, run_id) for arm in order]
    (s0_dir.parent / "arm_order.json").write_text(json.dumps({"seed": seed, "order": order}), encoding="utf-8")
    return {"task_id": task_id, "order": order, "rows": rows, "cost_usd": sum_cost(rows)["cost_usd"],
            "infra": any(r["infra"] for r in rows), "line": " ".join(f"{r['arm']}={r['outcome']}" for r in rows)}


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for arm in ARMS:
        a = [r for r in rows if r["arm"] == arm]
        if a:
            out[arm] = {"n": len(a), "hidden_pass": hidden_pass_rate(a, arm), "refused_rate": sum(r["budget_refused"] for r in a) / len(a),
                        **{"cost_cont_" + k: v for k, v in sum_cost([{"cost_usd": r["cost_cont_usd"]} for r in a]).items()},
                        "n_calls_mean": sum(r["n_calls"] for r in a) / len(a), "models": sorted({m for r in a for m in r["models"]})}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", choices=["bcb", "mbppplus"], required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--b-cont", type=float, required=True, help="계속 arm 추가 예산 USD (파일럿 0회차 B-expert 1회 비용 중앙값)")
    ap.add_argument("--a-call-median", type=float, required=True, help="A 1회 호출 비용 중앙값 USD (k 계산용)")
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--k-max", type=int, default=8)
    args = ap.parse_args()
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
    cfg = {"b_cont": args.b_cont, "a_call_median": args.a_call_median, "k_max": args.k_max, "stop_on_visible_pass": True, "min_max_tokens": MIN_MAX_TOKENS}
    root = Path(os.getenv("HARMONET_ARMS_ROOT") or (Path(__file__).resolve().parent.parent / "evidence" / "week2")) / run_id
    out = Path(args.output)

    def _write(task_rows, stopped):
        flat = [r for t in task_rows for r in t["rows"]]
        out.write_text(json.dumps({"run_id": run_id, "config": cfg, "seed": args.seed, "pool": args.pool, "ids_file": args.ids,
                                   "stopped_reason": stopped, "summary": summarize(flat) if flat else {}, "tasks": task_rows}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["task_id", "arm", "passed", "outcome", "visible_outcome", "n_calls", "budget_refused", "cost_cont_usd",
                                              "cost_usd", "models", "infra", "trace_path"], extrasaction="ignore")
            w.writeheader()
            w.writerows([{**r, "models": ",".join(r["models"])} for r in flat])

    run_loop(ids, lambda tid: run_task_all_arms(tid, tasks[tid][0], tasks[tid][1], clients, cfg, budget, root, run_id, args.seed), _write, budget, label="arms")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
