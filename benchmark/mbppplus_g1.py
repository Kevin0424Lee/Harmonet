"""
benchmark/mbppplus_g1.py — MBPP+ single 어댑터 러너 (Week2-B0). benchmark/lcb_g1.py 와 같은 흐름.

과제마다: single(builder) 1회 호출 → 코드 추출 → verify_visible(base) → 트레이스 종료 → score_hidden(plus − base) → TaskState.score(post_hoc).
지표: base_pass(공개 base 통과) / plus_only_pass(히든 plus−base 통과, **게이트 지표**) / both_pass(둘 다 = 공식 plus 판정과 동치).

    python -X utf8 -m benchmark.mbppplus_g1 --ids evidence/week2/probe_ids_mbppplus.json --output evidence/week2/pool_probe_mbppplus.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.agents_single import _DEFAULT_SYSTEM
from benchmark.hidden_guard import hidden_pass_rate
from benchmark.mbppplus import MbppTask, load_mbppplus
from benchmark.runloop import budgeted_generate, require_budget, run_loop
from harmonet.budget import Budget, budget_from_env
from harmonet.llm import get_llm_client
from harmonet.pricing import sum_cost
from harmonet.trace import NO_COST, TaskState, model_used, verify_cost
from harmonet.usage import METER
from harmonet.verify import extract_artifact, score_hidden, verify_visible

CSV_FIELDS = ["task_id", "entry_point", "base_pass", "plus_only_pass", "both_pass", "outcome", "visible_outcome", "n_base", "n_plus_only",
              "n_dup_removed", "prompt_tokens", "completion_tokens", "token_source", "cost_usd", "wall_ms", "extraction", "hidden_exposed",
              "trace_path", "candidate_code"]


def run_task(task: MbppTask, budget: Optional[Budget] = None) -> Dict[str, Any]:
    METER.reset()
    state = TaskState(task.task_id, system="single")
    client = get_llm_client("builder")
    spec = task.spec()
    spec_visible = {k: v for k, v in spec.items() if k != "hidden_tests"}   # 루프 안: base 만

    output, cost, _usd, wall = budgeted_generate(client, budget, task.prompt, _DEFAULT_SYSTEM, note=task.task_id)
    report: Dict[str, str] = {}
    code = extract_artifact(output, "code", report=report)
    state.artifact = code
    state.record("build", "builder", model_used("builder", client), cost, output[:200])

    visible = verify_visible(code, spec_visible)
    state.verification = visible
    state.record("verify", "validator", "none", verify_cost(visible), visible["evidence"][:400])
    state.record("terminate", "single", "none", NO_COST, "single call + visible verify; no revision")

    hidden = score_hidden(code, spec)   # 에피소드 종료 후에만
    state.set_score(hidden)
    trace_path = state.save()

    b = state.history[0]
    return {
        "task_id": task.task_id, "entry_point": task.entry_point,
        "base_pass": visible["passed"], "plus_only_pass": hidden["passed"], "both_pass": visible["passed"] and hidden["passed"],
        "passed": hidden["passed"], "outcome": hidden["outcome"], "visible_outcome": visible["outcome"],
        "n_base": len(task.tests), "n_plus_only": len(task.hidden_tests), "n_dup_removed": task.meta["n_dup_removed"],
        "prompt_tokens": b.cost["prompt_tokens"], "completion_tokens": b.cost["completion_tokens"], "token_source": b.token_source,
        "cost_usd": b.cost_usd, "wall_ms": b.cost["wall_ms"], "extraction": report.get("extraction", ""),
        "hidden_exposed": False, "trace_path": str(trace_path), "candidate_code": code, "infra": bool(visible.get("infra") or hidden.get("infra")),
        "line": f"base={visible['outcome']} plus_only={hidden['outcome']} {cost['prompt_tokens']}/{cost['completion_tokens']}tok",
    }


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    return {"n": n, "base_pass": sum(r["base_pass"] for r in rows) / n, "plus_only_pass": hidden_pass_rate(rows, "mbppplus"),
            "both_pass": sum(r["both_pass"] for r in rows) / n, **sum_cost(rows),
            "token_source": sorted({r["token_source"] for r in rows}), "extraction": sorted({r["extraction"] for r in rows}),
            "outcomes": {o: sum(r["outcome"] == o for r in rows) for o in sorted({r["outcome"] for r in rows})}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True, help="task_id 목록 JSON ({\"ids\": [...]}, 사전 등록 파일)")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    ids = json.loads(Path(args.ids).read_text(encoding="utf-8"))["ids"]
    by_id = {t.task_id: t for t in load_mbppplus(ids)}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"[mbppplus_g1] 스펙에 없는 id: {missing[:5]} …")

    budget = budget_from_env(os.getenv("HARMONET_TRACE_RUN_ID"))
    require_budget(budget)
    get_llm_client("builder")
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
    print(f"\nbase_pass={100 * s['base_pass']:.1f}%  plus_only_pass={100 * s['plus_only_pass']:.1f}%  both_pass={100 * s['both_pass']:.1f}%  "
          f"cost=${s['cost_usd']}  n_unpriced={s['n_unpriced']}  outcomes={s['outcomes']}")
    print(f"Saved: {out} / {out.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
