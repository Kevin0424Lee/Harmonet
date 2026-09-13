"""
tests/mbppplus_official_oracle.py — 동등성 테스트용 공식 오라클. **evalplus venv 로만** 실행된다 (test_mbppplus_equivalence.py 가 subprocess 로 호출).

stdin: {"entry_point", "code", "inputs": [repr…], "expected": [repr…], "atol"} → stdout: {"stat": "pass"|"fail"|"timeout", "details": [...]}

공식 evalplus.eval.unsafe_execute 를 그대로 호출하되, Windows 에 없는 두 플랫폼 가드만 no-op 으로 바꾼다:
  time_limit (SIGALRM 타이머) · reliability_guard (resource 모듈 rlimit). 비교 블록(집합·특수 판정·atol·np.allclose)은 손대지 않는다.
"""
import contextlib
import json
import math
import sys
from collections import Counter
from multiprocessing import Array, Value

import evalplus.eval as E

E.time_limit = lambda seconds: contextlib.nullcontext()
E.reliability_guard = lambda maximum_memory_bytes=None: None
ENV = {"__builtins__": {}, "inf": math.inf, "nan": math.nan, "Counter": Counter, "set": set}

req = json.loads(sys.stdin.read())
inputs = [eval(s, dict(ENV)) for s in req["inputs"]]
expected = [eval(s, dict(ENV)) for s in req["expected"]]
stat, progress = Value("i", E._UNKNOWN), Value("i", 0)
details = Array("b", [False] * len(inputs))
E.unsafe_execute("mbpp", req["entry_point"], req["code"], inputs, expected, [60.0] * len(inputs), req["atol"], False, stat, details, progress)
s = E._mapping[stat.value] or E.TIMEOUT
d = list(details[: progress.value])
if s == E.PASS and (len(d) != len(inputs) or not all(d)):
    s = E.FAIL
print(json.dumps({"stat": s, "details": [bool(x) for x in d]}))
