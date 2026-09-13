"""
scripts/mbppplus_canonical_check.py — 공식 정답(canonical_solution)이 우리 mbppplus 하네스에서 base·hidden 모두 pass 하는지 전수 확인.
전사·직렬화 오류가 있으면 여기서 드러난다. 정답 코드는 이 스크립트 밖(생성·수정·리뷰 경로)으로 나가지 않는다.

    python -X utf8 scripts/mbppplus_canonical_check.py > evidence/week2/mbppplus_canonical_check.txt
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from benchmark.mbppplus import load_mbppplus, load_spec   # noqa: E402
from harmonet.verify import score_hidden, verify_visible  # noqa: E402

CACHE = Path.home() / "AppData/Local/evalplus/evalplus/Cache/MbppPlus-v0.2.0.jsonl"
canon = {r["task_id"]: r["prompt"] + r["canonical_solution"] for r in map(json.loads, CACHE.read_text(encoding="utf-8").splitlines())}
spec = load_spec()
print("spec sha256 pinned; excluded:", spec["excluded"])
t0 = time.time(); bad = []
tasks = load_mbppplus()
for i, t in enumerate(tasks, 1):
    v = verify_visible(canon[t.task_id], t.spec()); h = score_hidden(canon[t.task_id], t.spec())
    if not (v["passed"] and h["passed"]):
        bad.append((t.task_id, v["outcome"], h["outcome"], h["evidence"][-200:]))
        print("FAIL", bad[-1], flush=True)
    if i % 50 == 0:
        print(f"{i}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)
print(f"canonical pass base&hidden: {len(tasks) - len(bad)}/{len(tasks)}  failures={bad}  {time.time() - t0:.0f}s")
