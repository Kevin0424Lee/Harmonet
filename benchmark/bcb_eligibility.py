"""
benchmark/bcb_eligibility.py — BigCodeBench 적격 풀 확정 (Week2-C0). 모델 성적과 무관. 무료.

    python -X utf8 -m benchmark.bcb_eligibility [--limit N] [--workers 4]

관문 1 (가시 검증 신호): doc_struct 예제에 기대 출력이 있고 ∧ 정적 스크린(난수·시간·네트워크·FS·플롯 토큰) 통과 ∧
         공식 이미지에서 canonical 로 doctest 를 2회 돌려 둘 다 pass. → 가시 테스트 ≥1 인 과제 수 보고 (260 미만이면 멈춤).
관문 2 (실행 안정성): 관문 1 과제의 canonical 을 공식 test 로 2회 채점해 둘 다 pass.
적격 풀 = 관문 1 ∧ 관문 2 − 개발용 ID. 결과: evidence/week2/bcb_eligibility.json (+ 배치 원본 benchmark_data/bcb/work/results.json).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from benchmark.bcb import BCB_FILE, BCB_REVISION, BCB_SHA256, load_bcb
from harmonet.verify import BCB_IMAGE_DEFAULT, bcb_docker_cmd

WORK = Path(__file__).resolve().parent.parent / "benchmark_data" / "bcb" / "work"
OUT = Path(__file__).resolve().parent.parent / "evidence" / "week2" / "bcb_eligibility.json"
DEV_IDS = ["BigCodeBench/0", "BigCodeBench/1", "BigCodeBench/2"]   # 로더 자체 점검·하네스 스모크에 쓴 과제 (풀에서 제외)
GATE1_MIN = 260


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-run", action="store_true", help="results.json 이 이미 있으면 집계만")
    args = ap.parse_args()

    tasks = load_bcb()
    cand = [t for t in tasks if t.doctest_src and not t.static_screen]
    if args.limit:
        cand = cand[: args.limit]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "tasks.json").write_text(json.dumps([
        {"task_id": t.task_id, "entry_point": t.entry_point, "code": t.prompt + "\n" + t._canonical,   # 공식 get_groundtruth 와 같은 조립
         "doctest_module": t.visible_tests()[0], "test": t._test} for t in cand], ensure_ascii=False), encoding="utf-8")
    print(f"tasks={len(tasks)} doctest_with_output={sum(bool(t.doctest_src) for t in tasks)} static_clean={len(cand)}")
    t0 = time.time()
    if not args.skip_run:
        import shutil
        shutil.copy(Path(__file__).parent / "bcb_batch_harness.py", WORK / "batch.py")
        cmd = bcb_docker_cmd(str(WORK), "batch.py") + [str(args.workers)]
        print("[docker]", " ".join(cmd[:12]), "…")
        with open(WORK / "batch.log", "a", encoding="utf-8") as log:
            rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
        print(f"batch rc={rc} {time.time() - t0:.0f}s")
    res = json.loads((WORK / "results.json").read_text(encoding="utf-8"))

    gate1 = [t.task_id for t in cand if res.get(t.task_id, {}).get("doctest") == ["pass", "pass"]]
    gate2 = [tid for tid in gate1 if res[tid]["test"] == ["pass", "pass"]]
    eligible = [tid for tid in gate2 if tid not in DEV_IDS]
    excluded = {tid: ("doctest " + str(res[tid]["doctest"]) if res.get(tid, {}).get("doctest") != ["pass", "pass"] else "test " + str(res[tid]["test"]))
                for tid in (t.task_id for t in cand) if tid in res and tid not in gate2}
    summary = {"source": {"repo": "bigcode/bigcodebench", "revision": BCB_REVISION, "file": BCB_FILE, "sha256": BCB_SHA256,
                          "image": BCB_IMAGE_DEFAULT, "date": time.strftime("%Y-%m-%d")},
               "n_total": len(tasks), "n_doctest_with_output": sum(bool(t.doctest_src) for t in tasks), "n_static_clean": len(cand),
               "n_checked": len([t for t in cand if t.task_id in res]), "gate1_visible_ge1": len(gate1), "gate1_min": GATE1_MIN,
               "gate1_pass": len(gate1) >= GATE1_MIN, "gate2_canonical_stable": len(gate2), "dev_ids": DEV_IDS, "n_eligible": len(eligible),
               "eligible_ids": eligible, "excluded": excluded, "static_screen_hits": {t.task_id: t.static_screen for t in tasks if t.doctest_src and t.static_screen}}
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"gate1 visible>=1: {len(gate1)} (min {GATE1_MIN}) | gate2 canonical stable: {len(gate2)} | eligible: {len(eligible)} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
