"""Week2-B0: 우리 mbppplus 하네스(전사 비교) vs 공식 evalplus unsafe_execute (evalplus venv, 플랫폼 가드만 stub) 판정 동등성.
케이스마다 두 쪽의 pass/fail 이 같아야 한다. evalplus venv 가 없으면 skip 하지 않고 실패한다(조용한 생략 금지)."""
import json
import subprocess
from pathlib import Path

import pytest

from harmonet.mbppplus_compare import atol_sequence
from harmonet.verify import verify_visible

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv-evalplus" / "Scripts" / "python.exe"
ORACLE = ROOT / "tests" / "mbppplus_official_oracle.py"


def official(entry, code, inputs, expected, atol):
    assert VENV_PY.exists(), f"evalplus venv 없음: {VENV_PY} (requirements-evalplus.txt 로 만들라)"
    p = subprocess.run([str(VENV_PY), "-X", "utf8", str(ORACLE)], input=json.dumps(
        {"entry_point": entry, "code": code, "inputs": inputs, "expected": expected, "atol": atol}),
        capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert p.returncode == 0, p.stderr[-500:]
    return json.loads(p.stdout.strip().splitlines()[-1])["stat"] == "pass"


def ours(entry, code, inputs, expected, atol):
    exps = [eval(e, {"__builtins__": {}, "inf": float("inf"), "nan": float("nan")}) for e in expected]  # 테스트 내부 신뢰 문자열
    cases = [{"input": i, "expected": e, "atol": a, "time_limit": 60.0} for i, e, a in zip(inputs, expected, atol_sequence(exps, atol))]
    r = verify_visible(code, {"kind": "mbppplus", "entry_point": entry, "tests": cases})
    return r["passed"], r


CASES = [
    # (이름, entry, code, inputs, expected, atol, 기대 판정)
    ("set_eq_task_order_differs", "similar_elements", "def similar_elements(a, b):\n    return tuple(x for x in b if x in a)\n",
     ["((3, 4, 5, 6), (5, 7, 4, 10))"], ["(4, 5)"], 0, True),
    ("set_eq_task_list_instead_of_tuple", "similar_elements", "def similar_elements(a, b):\n    return [x for x in b if x in a]\n",
     ["((3, 4, 5, 6), (5, 7, 4, 10))"], ["(4, 5)"], 0, True),
    ("non_set_task_tuple_vs_list_fails", "pair", "def pair(a, b):\n    return [a, b]\n", ["(1, 2)"], ["(1, 2)"], 0, False),
    ("float_within_auto_atol", "half", "def half(x):\n    return x / 2 + 1e-8\n", ["(3.0,)"], ["1.5"], 0, True),
    ("float_outside_auto_atol", "half", "def half(x):\n    return x / 2 + 1e-3\n", ["(3.0,)"], ["1.5"], 0, False),
    ("float_list_dataset_atol_1e-4", "scale", "def scale(xs):\n    return [x * 2 + 5e-5 for x in xs]\n", ["([1.0, 2.0],)"], ["[2.0, 4.0]"], 1e-4, True),
    ("special_sum_div_zero_passes", "sum_div", "def sum_div(n):\n    return 0\n", ["(8,)"], ["7"], 0, True),
    ("special_surface_area_alt_formula", "surface_Area", "import math\ndef surface_Area(b, h):\n    return round(b*b + 2*b*math.sqrt((b/2)**2 + h*h))\n",
     ["(3, 4)"], ["33"], 0, True),
    ("special_digit_distance_alt", "digit_distance_nums", "def digit_distance_nums(a, b):\n    a, b = str(a), str(b); m = max(len(a), len(b))\n    return sum(abs(int(x) - int(y)) for x, y in zip(a.zfill(m), b.zfill(m)))\n",
     ["(1, 2)", "(23, 56)", "(123, 256)"], ["1", "6", "7"], 0, True),
    ("not_none_task_match_object_passes", "check_str", "import re\ndef check_str(s):\n    return re.match('^[aeiou]', s)\n",
     ["('apple',)", "('xyz',)"], ["True", "False"], 0, True),
    ("not_none_task_wrong_bool_fails", "check_str", "def check_str(s):\n    return False\n", ["('apple',)"], ["True"], 0, False),
    ("atol_state_carries_from_earlier_float_case", "f", "def f(x):\n    return x if isinstance(x, float) else [1, 2.0000001]\n",
     ["(1.5,)", "(0,)"], ["1.5", "[1, 2]"], 0, True),          # 앞 케이스가 float → 이후 atol 1e-6 유지 → 두 번째도 allclose 로 통과
    ("atol_state_absent_when_float_case_comes_later", "f", "def f(x):\n    return x if isinstance(x, float) else [1, 2.0000001]\n",
     ["(0,)", "(1.5,)"], ["[1, 2]", "1.5"], 0, False),         # 순서를 바꾸면 첫 케이스는 atol 0 → 실패
    ("exception_in_candidate_fails", "g", "def g(x):\n    raise ValueError('boom')\n", ["(1,)"], ["1"], 0, False),
    ("are_equivalent_always_passes", "are_equivalent", "def are_equivalent(a, b):\n    return 'anything'\n", ["(6, 28)"], ["False"], 0, True),
]


@pytest.mark.parametrize("name,entry,code,inputs,expected,atol,want", CASES, ids=[c[0] for c in CASES])
def test_matches_official(name, entry, code, inputs, expected, atol, want):
    got_off = official(entry, code, inputs, expected, atol)
    got_ours, r = ours(entry, code, inputs, expected, atol)
    assert got_off == want, f"공식 오라클이 기대와 다름: {got_off}"
    assert got_ours == got_off, f"우리={got_ours} 공식={got_off}: {r['evidence'][-300:]}"


def test_time_limit_exceeded_is_fail_not_pass():
    r = verify_visible("import time\ndef s(x):\n    time.sleep(1.3)\n    return x\n",
                       {"kind": "mbppplus", "entry_point": "s", "tests": [{"input": "(1,)", "expected": "1", "atol": 0, "time_limit": 1.0}]})
    assert r["passed"] is False and "time limit" in r["evidence"], r["evidence"]


def test_candidate_cannot_override_comparator():
    cheat = "def mbpp_match(*a, **k):\n    return True\ndef parse_literal(s):\n    return 0\ndef s(x):\n    return 999\n"
    r = verify_visible(cheat, {"kind": "mbppplus", "entry_point": "s", "tests": [{"input": "(1,)", "expected": "1", "atol": 0, "time_limit": 1.0}]})
    assert r["passed"] is False, r["evidence"]
