"""
benchmark/bcb_eligibility.py — BigCodeBench 적격 풀 확정 (Week2-C0). 모델 성적과 무관. 무료.

    python -X utf8 -m benchmark.bcb_eligibility [--limit N] [--workers 4]

관문 1 (가시 검증 신호): doc_struct 예제에 기대 출력이 있고 ∧ 정적 스크린(난수·시간·네트워크·FS·플롯 토큰) 통과 ∧
         공식 이미지에서 canonical 로 doctest 를 2회 돌려 둘 다 pass. → 가시 테스트 ≥1 인 과제 수 보고 (260 미만이면 멈춤).
관문 2 (실행 안정성): 관문 1 과제의 canonical 을 공식 test 로 R회(F5: 3회) 채점해 전부 pass ∧ 이력(eligibility_history.json)의 어느 실행에서도
         non-pass 가 없음 (있으면 flaky 로 제외 — 예: BigCodeBench/497 은 예제가 오늘 요일에 의존).
적격 풀 = 관문 1 ∧ 관문 2 − 개발용 ID. 결과: evidence/week2/bcb_eligibility.json (+ 배치 원본 benchmark_data/bcb/work/results.json).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from benchmark.bcb import BCB_FILE, BCB_REVISION, BCB_SHA256, FILTER_VERSION, load_bcb
from harmonet.verify import BCB_IMAGE_DEFAULT, bcb_docker_cmd, bcb_image

WORK = Path(__file__).resolve().parent.parent / "benchmark_data" / "bcb" / "work"
CACHE = WORK / "eligibility_cache.json"
HISTORY = WORK / "eligibility_history.json"     # F5: 실행마다 과제별 판정을 누적 — 어느 실행에서든 non-pass 가 있으면 flaky 로 제외
N_REP = 3
OUT = Path(__file__).resolve().parent.parent / "evidence" / "week2" / "bcb_eligibility.json"
DEV_IDS = ["BigCodeBench/0", "BigCodeBench/1", "BigCodeBench/2", "BigCodeBench/3", "BigCodeBench/4", "BigCodeBench/9"]   # 로더·하네스·arms 스모크(D5)에 쓴 과제 (풀에서 제외)
GATE1_MIN = 260


def checker_version() -> str:
    """harmonet/bcb_check.py 의 CHECKER_VERSION (호스트에는 bigcodebench 가 없어 import 대신 텍스트에서 읽는다)."""
    src = (Path(__file__).resolve().parent.parent / "harmonet" / "bcb_check.py").read_text(encoding="utf-8")
    return re.search(r'CHECKER_VERSION = "([^"]+)"', src).group(1)


def config_hash(reps: int = N_REP) -> str:
    """적격성 캐시 키 (D2 ⑤): 데이터 revision·해시, 이미지 digest, 필터 버전, 채점기 버전, 반복 수(F5). 하나라도 바뀌면 캐시를 버린다."""
    cfg = {"revision": BCB_REVISION, "sha256": BCB_SHA256, "image": bcb_image(), "filter": FILTER_VERSION, "checker": checker_version(), "reps": reps}
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def cache_valid(cache: dict, h: str) -> bool:
    return isinstance(cache, dict) and cache.get("config_hash") == h and isinstance(cache.get("results"), dict)


def load_cache(h: str) -> dict:
    """캐시가 있고 config_hash 가 같을 때만 결과를 돌려준다. 아니면 {} (재실행)."""
    if CACHE.exists():
        c = json.loads(CACHE.read_text(encoding="utf-8"))
        if cache_valid(c, h):
            return c["results"]
        print(f"[cache] config_hash 불일치 ({c.get('config_hash', '')[:12]} != {h[:12]}) — 재실행")
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--reps", type=int, default=N_REP)
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
    h = config_hash(args.reps)
    cached = load_cache(h)
    (WORK / "results.json").write_text(json.dumps(cached), encoding="utf-8")   # 유효한 캐시만 이어서 실행, 아니면 빈 결과에서
    print(f"config_hash={h[:12]} cached={len(cached)}")
    t0 = time.time()
    if not args.skip_run:
        import shutil
        shutil.copy(Path(__file__).parent / "bcb_batch_harness.py", WORK / "batch.py")
        shutil.copy(Path(__file__).resolve().parent.parent / "harmonet" / "bcb_check.py", WORK / "bcb_check.py")
        cmd = bcb_docker_cmd(str(WORK), "batch.py") + [str(args.workers), str(args.reps)]
        print("[docker]", " ".join(cmd[:12]), "…")
        with open(WORK / "batch.log", "a", encoding="utf-8") as log:
            rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
        print(f"batch rc={rc} {time.time() - t0:.0f}s")
    res = json.loads((WORK / "results.json").read_text(encoding="utf-8"))
    CACHE.write_text(json.dumps({"config_hash": h, "config": {"revision": BCB_REVISION, "image": bcb_image(), "filter": FILTER_VERSION,
                                                              "checker": checker_version()}, "results": res}), encoding="utf-8")

    # F5: 이력 누적 (config_hash·날짜·판정). 적격 = 이번 실행 R회 전부 pass ∧ 이력의 어느 실행에서도 non-pass 없음 (있으면 flaky)
    hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {}
    stamp = time.strftime("%Y-%m-%dT%H:%M")
    for tid, r in res.items():
        entries = hist.setdefault(tid, [])
        if not any(e.get("config_hash") == h and e.get("doctest") == r["doctest"] and e.get("test") == r["test"] for e in entries):
            entries.append({"config_hash": h, "date": stamp, "doctest": r["doctest"], "test": r["test"]})
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")

    def all_pass(v):
        return bool(v) and all(x == "pass" for x in v)

    def flaky(tid):
        return any(not all_pass(e["doctest"]) or not all_pass(e["test"]) for e in hist.get(tid, []) if e.get("doctest") is not None)

    gate1 = [t.task_id for t in cand if all_pass(res.get(t.task_id, {}).get("doctest", []))]
    gate2 = [tid for tid in gate1 if all_pass(res[tid]["test"])]
    stable = [tid for tid in gate2 if not flaky(tid)]
    eligible = [tid for tid in stable if tid not in DEV_IDS]
    excluded = {}
    for tid in (t.task_id for t in cand):
        if tid not in res:
            continue
        if not all_pass(res[tid]["doctest"]):
            excluded[tid] = "doctest " + str(res[tid]["doctest"])
        elif not all_pass(res[tid]["test"]):
            excluded[tid] = "test " + str(res[tid]["test"])
        elif flaky(tid):
            excluded[tid] = "flaky: 이력 불일치 " + str([(e["date"], e["doctest"], e["test"]) for e in hist[tid] if not (all_pass(e["doctest"]) and all_pass(e["test"]))])[:200]
    summary = {"source": {"repo": "bigcode/bigcodebench", "revision": BCB_REVISION, "file": BCB_FILE, "sha256": BCB_SHA256,
                          "image": BCB_IMAGE_DEFAULT, "date": time.strftime("%Y-%m-%d"), "filter": FILTER_VERSION, "checker": checker_version(),
                          "config_hash": h},
               "n_total": len(tasks), "n_doctest_with_output": sum(bool(t.doctest_src) for t in tasks), "n_static_clean": len(cand),
               "n_checked": len([t for t in cand if t.task_id in res]), "gate1_visible_ge1": len(gate1), "gate1_min": GATE1_MIN,
               "gate1_pass": len(gate1) >= GATE1_MIN, "gate2_canonical_stable": len(gate2), "n_history_stable": len(stable), "n_rep": args.reps,
               "dev_ids": DEV_IDS, "n_eligible": len(eligible),
               "eligible_ids": eligible, "excluded": excluded, "static_screen_hits": {t.task_id: t.static_screen for t in tasks if t.doctest_src and t.static_screen}}
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"gate1 visible>=1: {len(gate1)} (min {GATE1_MIN}) | gate2 canonical stable: {len(gate2)} | history-stable: {len(stable)} | eligible: {len(eligible)} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
