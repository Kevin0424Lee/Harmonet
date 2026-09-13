"""
benchmark/mbppplus_gt.py — MBPP+ 스펙(정답 출력) 생성기 (Week2-B0). **evalplus venv 에서만** 실행한다.

    .venv-evalplus/Scripts/python.exe -X utf8 -m benchmark.mbppplus_gt

공식 evalplus==0.3.1 의 get_mbpp_plus(역직렬화 포함)·trusted_exec(정답 실행, 시간 기록)·특수 오라클 상수를 그대로 써서
과제별 케이스를 만든다. 산출물 benchmark_data/mbppplus/MbppPlus-v0.2.0.spec.json (gitignore, 해시는 evidence/week2/mbppplus_source.md).

케이스 = {"input": repr, "expected": repr, "atol": 케이스 적용 atol, "time_limit": max(1, 4×정답시간)}  (공식 untrusted_check 와 동일 규칙)
  tests        = base_input 전부 (프롬프트에 노출된 3개 assert 의 입력 = 공식 "base" 판정)
  hidden_tests = plus_input 중 base_input 과 repr 이 같은 입력을 뺀 것 (n_dup_removed 기록) = 공식 "plus" 판정에서 base 를 뺀 것
  atol 은 공식 루프의 상태 전이(atol==0 이고 기대값이 float 이면 이후 1e-6)를 base·plus 각각 순서대로 재현해 케이스에 붙인다.

제외(사유를 excluded 에 기록): 정답 실행 실패, repr 총량 > SIZE_CAP (Mbpp/255 는 1.29GB, Mbpp/630 은 11MB — JSON 스펙에 못 넣는다),
  repr 왕복 실패(parse_literal 로 복원해 값·타입이 다르면).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from evalplus.data import get_mbpp_plus                      # 공식 로더 (역직렬화 특수 케이스 포함)
from evalplus.data.mbpp import MBPP_PLUS_VERSION
from evalplus.eval._special_oracle import MBPP_OUTPUT_NOT_NONE_TASKS
from evalplus.gen.util import trusted_exec                   # 공식 정답 실행기 (deepcopy 입력, 시간 기록)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harmonet.mbppplus_compare import atol_sequence, parse_literal  # noqa: E402  (main 환경과 같은 복원 규칙으로 왕복 검증)

CACHE_FILE = Path.home() / "AppData/Local/evalplus/evalplus/Cache" / f"MbppPlus-{MBPP_PLUS_VERSION}.jsonl"
CACHE_SHA256 = "ee1701c904eb306523280b5a38a661d13248d16dd92d2e4fe2de36b519d3c413"   # 2026-09-13 확인
SOURCE_URL = f"https://github.com/evalplus/mbppplus_release/releases/download/{MBPP_PLUS_VERSION}/MbppPlus.jsonl.gz"
OUT = Path(__file__).resolve().parent.parent / "benchmark_data" / "mbppplus" / f"MbppPlus-{MBPP_PLUS_VERSION}.spec.json"
SIZE_CAP = 1_000_000          # 과제당 repr 총 바이트 상한
MIN_TIME_LIMIT, GT_TIME_LIMIT_FACTOR = 1.0, 4.0   # evalplus.config 기본값


def _cases(inputs, outs, times, atol0):
    return [{"input": repr(inp), "expected": repr(out), "atol": atol, "time_limit": max(MIN_TIME_LIMIT, GT_TIME_LIMIT_FACTOR * t)}
            for inp, out, t, atol in zip(inputs, outs, times, atol_sequence(outs, atol0))]


def _roundtrip_ok(cases, originals) -> bool:
    """복원값이 원본과 == 이고 타입이 같아야 한다. repr 문자열 자체는 달라질 수 있다(집합 순서·복소수 -0)."""
    for c, (inp, out) in zip(cases, originals):
        for k, x in (("input", inp), ("expected", out)):
            y = parse_literal(c[k])
            if not (y == x and type(y) == type(x)):
                return False
    return True


def main() -> int:
    h = hashlib.sha256(CACHE_FILE.read_bytes()).hexdigest()
    if h != CACHE_SHA256:
        raise SystemExit(f"[mbppplus_gt] 데이터 해시 불일치: {h} != {CACHE_SHA256} ({CACHE_FILE})")
    problems = get_mbpp_plus()
    tasks, excluded = {}, {}
    t_all = time.time()
    for tid, p in problems.items():
        onn = p["entry_point"] in MBPP_OUTPUT_NOT_NONE_TASKS
        plus_in = p["plus_input"] if isinstance(p["plus_input"], list) else list(p["plus_input"].values())
        code = p["prompt"] + p["canonical_solution"]
        try:
            base_out, base_t = trusted_exec(code, p["base_input"], p["entry_point"], record_time=True, output_not_none=onn)
            plus_out, plus_t = trusted_exec(code, plus_in, p["entry_point"], record_time=True, output_not_none=onn)
        except BaseException as e:  # noqa: BLE001
            excluded[tid] = f"canonical exec failed: {type(e).__name__}: {str(e)[:80]}"; continue
        size = sum(len(repr(x)) for x in p["base_input"] + plus_in + base_out + plus_out)
        if size > SIZE_CAP:
            excluded[tid] = f"repr size {size} > cap {SIZE_CAP}"; continue
        base = _cases(p["base_input"], base_out, base_t, p["atol"])
        plus_all = _cases(plus_in, plus_out, plus_t, p["atol"])
        base_reprs = {c["input"] for c in base}
        keep = [i for i, c in enumerate(plus_all) if c["input"] not in base_reprs]
        hidden = [plus_all[i] for i in keep]
        originals = list(zip(p["base_input"], base_out)) + [(plus_in[i], plus_out[i]) for i in keep]
        if not _roundtrip_ok(base + hidden, originals):
            excluded[tid] = "repr round-trip failed"; continue
        tasks[tid] = {"entry_point": p["entry_point"], "prompt": p["prompt"], "assertion": p["assertion"], "atol": p["atol"],
                      "tests": base, "hidden_tests": hidden, "n_plus_total": len(plus_all), "n_dup_removed": len(plus_all) - len(hidden)}
    spec = {"source": {"dataset": "MBPP+", "version": MBPP_PLUS_VERSION, "file": CACHE_FILE.name, "sha256": CACHE_SHA256, "url": SOURCE_URL,
                       "evalplus": "0.3.1", "generated": time.strftime("%Y-%m-%d")},
            "rules": {"time_limit": f"max({MIN_TIME_LIMIT}, {GT_TIME_LIMIT_FACTOR}*canonical_time)", "size_cap": SIZE_CAP},
            "n_tasks": len(tasks), "excluded": excluded, "tasks": tasks}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"tasks={len(tasks)} excluded={excluded} hidden_total={sum(len(t['hidden_tests']) for t in tasks.values())} "
          f"dup_removed={sum(t['n_dup_removed'] for t in tasks.values())} {time.time() - t_all:.0f}s")
    print(f"spec: {OUT} sha256={hashlib.sha256(OUT.read_bytes()).hexdigest()} bytes={OUT.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
