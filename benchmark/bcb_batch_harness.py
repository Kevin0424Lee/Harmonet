"""
benchmark/bcb_batch_harness.py — BCB 적격성 배치 (Week2-C0 2-3·2-4, D2 ⑤). **공식 이미지 안에서** 실행 (bcb_eligibility.py 가 docker 로 띄움).

입력 /w/tasks.json: [{"task_id", "entry_point", "code"(canonical 전체 프로그램), "doctest_module"|null, "test"(공식)}]
과제마다 D2 채점기(`harmonet/bcb_check.py` 사본 — 공식 환경 헬퍼 + 실행 수 검사)로 doctest 모듈 R회 + 공식 test R회 판정 (F5: R=3) → /w/results.json
(과제 끝날 때마다 갱신). canonical 은 여기(적격성)에서만 실행되고 모델에는 가지 않는다.

병렬화는 **비데몬 워커 프로세스** N 개 (스레드 아님): 스레드에서 fork 한 자식은 이 이미지의 Python 3.10 에서 정상 종료해도 exitcode 1 로
끝나 D2 의 exitcode 규칙에 걸린다 (D2 에서 확인). Pool 워커는 데몬이라 자식을 못 만든다 → 직접 Process + Queue.
"""
import json
import multiprocessing
import sys
import time

sys.path.insert(0, "/w")
from bcb_check import CHECKER_VERSION, LIMITS, check   # D2 채점기 (실행 수 검사) — 채점과 같은 판정으로 적격성을 본다


def _check(code, test, entry):
    t0 = time.time()
    stat, counts, expected, details = check(code, test, LIMITS)
    return stat, round(time.time() - t0, 2), {"expected": expected, **counts, **{k: str(v)[:200] for k, v in list(details.items())[:3]}}


def worker(q_in, q_out, n_rep):
    while True:
        t = q_in.get()
        if t is None:
            return
        r = {"doctest": [], "test": [], "doctest_time": [], "test_time": [], "detail": {}, "n_rep": n_rep}
        if t["doctest_module"]:
            for _ in range(n_rep):
                s, dt, d = _check(t["code"], t["doctest_module"], t["entry_point"]); r["doctest"].append(s); r["doctest_time"].append(dt)
                if s != "pass": r["detail"]["doctest"] = d
        for _ in range(n_rep):
            s, dt, d = _check(t["code"], t["test"], t["entry_point"]); r["test"].append(s); r["test_time"].append(dt)
            if s != "pass": r["detail"]["test"] = d
        q_out.put((t["task_id"], r))


if __name__ == "__main__":
    multiprocessing.set_start_method("fork", force=True)
    tasks = json.load(open("/w/tasks.json", encoding="utf-8"))
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    n_rep = int(sys.argv[2]) if len(sys.argv) > 2 else 3          # F5: 3회 실행 전부 pass 여야 적격
    try:
        results = json.load(open("/w/results.json", encoding="utf-8"))   # 이어서 실행 (호스트가 유효한 캐시만 넣어 준다)
    except Exception:
        results = {}
    todo = [t for t in tasks if t["task_id"] not in results]
    print("checker", CHECKER_VERSION, "todo", len(todo), "cached", len(results), flush=True)
    q_in, q_out = multiprocessing.Queue(), multiprocessing.Queue()
    procs = [multiprocessing.Process(target=worker, args=(q_in, q_out, n_rep)) for _ in range(workers)]
    for p in procs:
        p.start()
    for t in todo:
        q_in.put(t)
    for _ in procs:
        q_in.put(None)
    for _ in range(len(todo)):
        tid, r = q_out.get()
        results[tid] = r
        with open("/w/results.json", "w", encoding="utf-8") as f:
            json.dump(results, f)
        print(f"{len(results)}/{len(tasks)} {tid} doctest={r['doctest']} test={r['test']}", flush=True)
    for p in procs:
        p.join()
    print("done", len(results), flush=True)
