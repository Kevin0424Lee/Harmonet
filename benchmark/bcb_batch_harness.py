"""
benchmark/bcb_batch_harness.py — BCB 적격성 배치 (Week2-C0 2-3·2-4). **공식 이미지 안에서** 실행 (bcb_eligibility.py 가 docker 로 띄움).

입력 /w/tasks.json: [{"task_id", "entry_point", "code"(canonical 전체 프로그램), "doctest_module"|null, "test"(공식)}]
과제마다 공식 `bigcodebench.eval.untrusted_check` 로  doctest 모듈 2회 + 공식 test 2회 판정 → /w/results.json (과제 끝날 때마다 갱신).
canonical 은 여기(적격성)에서만 실행되고 모델에는 가지 않는다.
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from bigcodebench.eval import untrusted_check

LIMITS = dict(max_as_limit=30 * 1024, max_data_limit=30 * 1024, max_stack_limit=10, min_time_limit=1.0, gt_time_limit=1.0)
tasks = json.load(open("/w/tasks.json", encoding="utf-8"))
workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
results, lock = {}, threading.Lock()
try:
    results = json.load(open("/w/results.json", encoding="utf-8"))   # 이어서 실행
except Exception:
    results = {}


def _check(code, test, entry):
    t0 = time.time()
    stat, details = untrusted_check(code, test, entry, **LIMITS)
    return stat, round(time.time() - t0, 2), {k: str(v)[:200] for k, v in list(details.items())[:3]}


def run(t):
    if t["task_id"] in results:
        return
    r = {"doctest": [], "test": [], "doctest_time": [], "test_time": [], "detail": {}}
    if t["doctest_module"]:
        for _ in range(2):
            s, dt, d = _check(t["code"], t["doctest_module"], t["entry_point"]); r["doctest"].append(s); r["doctest_time"].append(dt)
            if s != "pass": r["detail"]["doctest"] = d
    for _ in range(2):
        s, dt, d = _check(t["code"], t["test"], t["entry_point"]); r["test"].append(s); r["test_time"].append(dt)
        if s != "pass": r["detail"]["test"] = d
    with lock:
        results[t["task_id"]] = r
        with open("/w/results.json", "w", encoding="utf-8") as f:
            json.dump(results, f)
        print(f"{len(results)}/{len(tasks)} {t['task_id']} doctest={r['doctest']} test={r['test']}", flush=True)


with ThreadPoolExecutor(max_workers=workers) as ex:
    list(ex.map(run, tasks))
print("done", len(results), flush=True)
