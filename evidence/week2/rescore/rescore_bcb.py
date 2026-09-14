"""
evidence/week2/rescore/rescore_bcb.py — 프로브 4(BCB A/B 120 후보)를 D2 채점기(실행 수 검사 + 사전 바인딩)로 재채점. 유료 호출 0.

    python -X utf8 evidence/week2/rescore/rescore_bcb.py
출력: evidence/week2/rescore/rescore_bcb.json + RESCORE_bcb.md (뒤집힌 행 수·사유). 원 프로브 파일은 손대지 않는다 (사전 등록 판정 보존).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmark.bcb import load_bcb                 # noqa: E402
from harmonet.verify import score_hidden           # noqa: E402

OUT = Path(__file__).resolve().parent
rows_all = []
for arm in "AB":
    d = json.loads((ROOT / "evidence/week2" / f"pool_probe_bcb_{arm}.json").read_text(encoding="utf-8"))
    for r in d["rows"]:
        rows_all.append((arm, r))
tasks = {t.task_id: t for t in load_bcb(sorted({r["task_id"] for _, r in rows_all}))}
out = []
t0 = time.time()
for i, (arm, r) in enumerate(rows_all, 1):
    t = tasks[r["task_id"]]
    h = score_hidden(r["candidate_code"], t.spec(visible=False))
    out.append({"arm": arm, "task_id": r["task_id"], "old_outcome": r["outcome"], "old_passed": r["passed"], "new_outcome": h["outcome"],
                "new_passed": h["passed"], "n_run": h["n_run"], "infra": h["infra"], "evidence": h["evidence"][-300:]})
    flag = "" if h["passed"] == r["passed"] else "  <-- FLIP"
    print(f"{i}/{len(rows_all)} {arm} {r['task_id']} old={r['outcome']} new={h['outcome']} n_run={h['n_run']}{flag}", flush=True)
(OUT / "rescore_bcb.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
flips = [o for o in out if o["new_passed"] != o["old_passed"]]
infra = [o for o in out if o["infra"]]
lines = ["# RESCORE_bcb — 프로브 4 후보 120개를 D2 채점기로 재채점 (%s)" % time.strftime("%Y-%m-%d"), "",
         "채점기: `harmonet/bcb_harness.py` (실행 수 검사 testsRun == expected ∧ skipped == 0 ∧ 정상 종료 + unittest 참조 사전 바인딩). 공식 이미지 동일.",
         "원 프로브 결과(`pool_probe_bcb_{A,B}.json`, 사전 등록 판정)는 수정하지 않는다.", "",
         f"- 재채점 행: {len(out)} (A 60 / B 60), 소요 {time.time() - t0:.0f}s, infra=True 행: {len(infra)}",
         f"- **뒤집힌 행: {len(flips)}**"]
for arm in "AB":
    o = [x for x in out if x["arm"] == arm]
    lines.append(f"- {arm}: 원 pass {sum(x['old_passed'] for x in o)}/60 → 재채점 pass {sum(x['new_passed'] for x in o)}/60")
if flips:
    lines += ["", "| arm | task | 원 | 재채점 | n_run | 사유(evidence 끝) |", "|---|---|---|---|---|---|"]
    for f in flips:
        lines.append(f"| {f['arm']} | {f['task_id']} | {f['old_outcome']} | {f['new_outcome']} | {f['n_run']} | {f['evidence'][-160:].replace('|', '/')} |")
else:
    lines.append("- 뒤집힌 행 없음: 120 후보 중 unittest 를 패치하거나 실행 수를 줄인 후보가 없었다는 뜻이며, 검사가 필요 없었다는 뜻은 아니다.")
(OUT.parent / "RESCORE_bcb.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines[4:]))
