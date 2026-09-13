"""
benchmark/lcb_g1.py — LiveCodeBench single 어댑터 러너 (Week2-A0)

과제마다: single(builder 역할) 1회 호출 → 후보 코드 추출·저장 → verify_visible(public) → 트레이스 종료 → score_hidden(private)
→ TaskState.score(post_hoc). 프롬프트에는 문제 설명 + public 예제만. private 테스트는 프롬프트·루프 어디에도 없다.

    python -X utf8 -m benchmark.lcb_g1 --ids evidence/week2/probe_ids.json --output evidence/week2/lcb_probe.json
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from benchmark.agents_single import _DEFAULT_SYSTEM
from benchmark.lcb import LcbTask, load_lcb
from harmonet.llm import get_llm_client
from harmonet.trace import NO_COST, TaskState, meter_delta, model_used, verify_cost
from harmonet.usage import METER
from harmonet.verify import extract_artifact, score_hidden, verify_visible

CSV_FIELDS = ["question_id", "difficulty", "contest_date", "platform", "passed", "outcome", "visible_outcome", "visible_n_passed",
              "n_public", "n_private", "prompt_tokens", "completion_tokens", "token_source", "cost_usd", "wall_ms", "extraction",
              "hidden_exposed", "trace_path", "candidate_code"]


def run_task(task: LcbTask, per_test_timeout_s: float = 10.0) -> Dict[str, Any]:
    METER.reset()
    state = TaskState(task.question_id, system="single")
    client = get_llm_client("builder")
    spec_public = {"kind": "stdio", "tests": task.public_tests, "per_test_timeout_s": per_test_timeout_s}   # 루프 안: public 만

    before = METER.snapshot("builder")
    t0 = time.perf_counter()
    output = client.generate(task.prompt, system_prompt=_DEFAULT_SYSTEM)
    wall = int((time.perf_counter() - t0) * 1000)
    report: Dict[str, str] = {}
    code = extract_artifact(output or "", "code", report=report)
    state.artifact = code
    state.record("build", "builder", model_used("builder", client), meter_delta(before, METER.snapshot("builder"), wall_ms=wall), (output or "")[:200])

    visible = verify_visible(code, spec_public, timeout_s=60.0)
    state.verification = visible
    state.record("verify", "validator", "none", verify_cost(visible), visible["evidence"][:400])
    state.record("terminate", "single", "none", NO_COST, "single call + visible verify; no revision")

    hidden = score_hidden(code, task.spec(), timeout_s=60.0)   # 에피소드 종료 후에만
    state.set_score(hidden)
    trace_path = state.save()

    b = state.history[0]
    return {
        "question_id": task.question_id, "difficulty": task.difficulty, "contest_date": task.contest_date, "platform": task.platform,
        "passed": hidden["passed"], "outcome": hidden["outcome"], "visible_outcome": visible["outcome"], "visible_n_passed": visible["n_passed"],
        "n_public": len(task.public_tests), "n_private": len(task.private_tests),
        "prompt_tokens": b.cost["prompt_tokens"], "completion_tokens": b.cost["completion_tokens"], "token_source": b.token_source,
        "cost_usd": b.cost_usd, "wall_ms": b.cost["wall_ms"], "extraction": report.get("extraction", ""),
        "hidden_exposed": False, "trace_path": str(trace_path), "candidate_code": code,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True, help="question_id 목록 JSON (사전 등록 파일)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--files", default="test5.jsonl,test6.jsonl")
    ap.add_argument("--per-test-timeout", type=float, default=10.0)
    args = ap.parse_args()

    from harmonet.embed import assert_embedding_sane  # noqa: F401  (single 은 임베딩을 쓰지 않으므로 게이트 생략)
    ids = json.loads(Path(args.ids).read_text(encoding="utf-8"))
    by_id = {t.question_id: t for t in load_lcb(args.files.split(","))}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"[lcb_g1] 데이터에 없는 id: {missing[:5]} …")

    rows: List[Dict[str, Any]] = []
    out = Path(args.output)
    for k, qid in enumerate(ids, 1):
        r = run_task(by_id[qid], args.per_test_timeout)
        rows.append(r)
        print(f"[single] {k}/{len(ids)} {qid} {r['difficulty']} hidden={r['outcome']} visible={r['visible_outcome']} "
              f"{r['prompt_tokens']}/{r['completion_tokens']}tok ${r['cost_usd']}")
    out.write_text(json.dumps({"ids_file": args.ids, "n": len(rows), "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    n_pass = sum(r["passed"] for r in rows)
    print(f"\nhidden pass {n_pass}/{len(rows)} = {100 * n_pass / max(1, len(rows)):.1f}%  cost=${sum(r['cost_usd'] or 0 for r in rows):.3f}")
    print(f"Saved: {out} / {out.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
