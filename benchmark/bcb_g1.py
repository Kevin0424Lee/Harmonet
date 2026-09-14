"""
benchmark/bcb_g1.py — BigCodeBench single 어댑터 러너 (Week2-C0). mbppplus_g1 과 같은 흐름, 판정만 공식 이미지(kind bcb).

과제마다: single(builder) 1회 호출 → 코드 추출 → verify_visible(doctest TestCases, 적격 과제만) → 종료 → score_hidden(공식 test) → post_hoc.
프롬프트 = complete_prompt 그대로 (가시 예제는 이미 docstring 에 있음). 모델은 HARMONET_MODEL_BUILDER 로 지정 (A/B 는 두 번 실행).

    python -X utf8 -m benchmark.bcb_g1 --ids evidence/week2/probe_ids_bcb.json --output evidence/week2/pool_probe_bcb_A.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.agents_single import _DEFAULT_SYSTEM
from benchmark.bcb import BcbTask, bcb_preflight, load_bcb
from benchmark.hidden_guard import hidden_pass_rate
from benchmark.runloop import budgeted_generate, require_budget, run_loop
from harmonet.budget import Budget, budget_from_env
from harmonet.llm import get_llm_client
from harmonet.pricing import sum_cost
from harmonet.trace import NO_COST, TaskState, model_used, verify_cost
from harmonet.usage import METER
from harmonet.verify import extract_artifact, score_hidden, verify_visible

CSV_FIELDS = ["task_id", "entry_point", "model", "passed", "outcome", "visible_outcome", "libs", "prompt_tokens", "completion_tokens",
              "token_source", "cost_usd", "wall_ms", "extraction", "hidden_exposed", "trace_path", "candidate_code"]


def run_task(task: BcbTask, budget: Optional[Budget] = None) -> Dict[str, Any]:
    METER.reset()
    state = TaskState(task.task_id, system="single")
    client = get_llm_client("builder")
    spec = task.spec(visible=True)
    spec_visible = {k: v for k, v in spec.items() if k != "hidden_tests"}   # 루프 안: 가시 doctest 만

    output, cost, _usd, wall = budgeted_generate(client, budget, task.prompt, _DEFAULT_SYSTEM, note=task.task_id)   # 예산 예약 → 호출 → 실측 가산
    report: Dict[str, str] = {}
    code = extract_artifact(output, "code", report=report)
    state.artifact = code
    model = model_used("builder", client)
    state.record("build", "builder", model, cost, output[:200])

    visible = verify_visible(code, spec_visible)
    state.verification = visible
    state.record("verify", "validator", "none", verify_cost(visible), visible["evidence"][:400])
    state.record("terminate", "single", "none", NO_COST, "single call + visible verify; no revision")

    hidden = score_hidden(code, spec)   # 에피소드 종료 후에만, 공식 이미지
    state.set_score(hidden)
    trace_path = state.save()

    b = state.history[0]
    return {"task_id": task.task_id, "entry_point": task.entry_point, "model": model, "passed": hidden["passed"], "outcome": hidden["outcome"],
            "visible_outcome": visible["outcome"], "libs": ",".join(task.libs), "infra": bool(visible.get("infra") or hidden.get("infra")),
            "line": f"visible={visible['outcome']} hidden={hidden['outcome']} {cost['prompt_tokens']}/{cost['completion_tokens']}tok",
            "prompt_tokens": b.cost["prompt_tokens"], "completion_tokens": b.cost["completion_tokens"], "token_source": b.token_source,
            "cost_usd": b.cost_usd, "wall_ms": b.cost["wall_ms"], "extraction": report.get("extraction", ""),
            "hidden_exposed": False, "trace_path": str(trace_path), "candidate_code": code}


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    return {"n": n, "hidden_pass": hidden_pass_rate(rows, "bcb"), "visible_pass": sum(r["visible_outcome"] == "pass" for r in rows) / n,
            **sum_cost(rows), "models": sorted({r["model"] for r in rows}),
            "token_source": sorted({r["token_source"] for r in rows}), "extraction": sorted({r["extraction"] for r in rows}),
            "outcomes": {o: sum(r["outcome"] == o for r in rows) for o in sorted({r["outcome"] for r in rows})},
            "visible_outcomes": {o: sum(r["visible_outcome"] == o for r in rows) for o in sorted({r["visible_outcome"] for r in rows})}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    ids = json.loads(Path(args.ids).read_text(encoding="utf-8"))["ids"]
    by_id = {t.task_id: t for t in load_bcb(ids)}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"[bcb_g1] 데이터에 없는 id: {missing[:5]} …")
    budget = budget_from_env(os.getenv("HARMONET_TRACE_RUN_ID"))
    require_budget(budget)                          # 유료 백엔드는 원장 없이 돌지 않는다 (D1 ①)
    get_llm_client("builder")                       # 모델 가용성 + 가격 사전 점검 (실패 시 호출 0회)
    print("[preflight]", bcb_preflight(), flush=True)   # docker 데몬·이미지 digest·canonical 1개 채점 (D1 ②)

    out = Path(args.output)

    def _write(rows, stopped):
        s = summarize(rows) if rows else {"n": 0}
        s["stopped_reason"] = stopped
        out.write_text(json.dumps({"ids_file": args.ids, "summary": s, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return s

    rows, _ = run_loop(ids, lambda tid: run_task(by_id[tid], budget), _write, budget)
    s = summarize(rows)
    print(f"\nhidden_pass={100 * s['hidden_pass']:.1f}%  visible_pass={100 * s['visible_pass']:.1f}%  cost=${s['cost_usd']}  "
          f"n_unpriced={s['n_unpriced']}  outcomes={s['outcomes']}")
    print(f"Saved: {out} / {out.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
