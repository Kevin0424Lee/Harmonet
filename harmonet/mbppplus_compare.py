"""
harmonet/mbppplus_compare.py — MBPP+ 공식 판정 로직 전사 (Week2-B0)

원본: evalplus==0.3.1  evalplus/eval/__init__.py::unsafe_execute 의 비교 블록 (dataset=="mbpp" 경로) 과
      evalplus/eval/_special_oracle.py 의 상수·오라클 함수. 단순 == 로 대체하지 않는다.
이 파일은 하네스 프렐류드로 **소스째** 삽입되므로 표준 라이브러리 + numpy(공식과 같은 np.allclose) 외 import 금지.

공식과의 차이 (전부 기록):
  - atol 이 입력 순서에 따라 바뀌는 상태(atol==0 이고 기대값이 float 이면 이후 1e-6 유지)는 스펙 생성 시 케이스별로 미리 계산해
    넣는다(mbppplus_gt.py). 여기서는 케이스에 붙은 atol 을 그대로 쓴다.
  - 입력·기대값은 repr 문자열로 저장하고 parse_literal 로 복원한다(inf/nan/Counter/set() 은 ast.literal_eval 이 못 읽으므로 제한 eval).
"""
from __future__ import annotations

import math
from collections import Counter

# ── evalplus/eval/_special_oracle.py 그대로 ──
MBPP_OUTPUT_NOT_NONE_TASKS = ["check_str", "text_match_three", "text_starta_endb"]
MBPP_OUTPUT_SET_EQ_TASKS = ["similar_elements", "find_char_long", "common_in_nested_lists", "extract_singly",
                            "larg_nnum", "intersection_array", "find_dissimilar", "Diff"]


def _surface_Area(base_edge, height):
    slant_height = math.sqrt((base_edge / 2) ** 2 + height ** 2)
    base_area = base_edge ** 2
    lateral_area = 4 * (base_edge * slant_height) / 2
    total_surface_area = base_area + lateral_area
    return round(total_surface_area)


def _digit_distance_nums(num1, num2):
    str_num1, str_num2 = str(num1), str(num2)
    max_length = max(len(str_num1), len(str_num2))
    str_num1, str_num2 = str_num1.zfill(max_length), str_num2.zfill(max_length)
    total_difference = 0
    for digit1, digit2 in zip(str_num1, str_num2):
        difference = abs(int(digit1) - int(digit2))
        total_difference += difference
    return total_difference


# ── evalplus/eval/__init__.py::is_floats 그대로 (ndarray 분기는 후보 반환값에 한해 동일하게 둔다) ──
def is_floats(x) -> bool:
    if isinstance(x, float):
        return True
    if isinstance(x, (list, tuple)) and x:
        return all(isinstance(i, float) for i in x)
    try:
        import numpy as np
        if isinstance(x, np.ndarray):
            return x.dtype == np.float64 or x.dtype == np.float32
    except ImportError:
        pass
    return False


def next_atol(atol, exp) -> float:
    """공식 루프의 atol 상태 전이: `if atol == 0 and is_floats(exp): atol = 1e-6` (이후 케이스에도 유지)."""
    return 1e-6 if (atol == 0 and is_floats(exp)) else atol


def atol_sequence(expecteds, atol0):
    """케이스 i 에 적용되는 atol 목록. 공식 루프에서 atol 은 케이스 i 판정 **뒤에** 전이되어 i+1 부터 적용된다."""
    out, atol = [], atol0
    for exp in expecteds:
        out.append(atol)
        atol = next_atol(atol, exp)
    return out


def mbpp_match(entry_point: str, inp, out, exp, atol) -> bool:
    """unsafe_execute 의 dataset=="mbpp" 비교 블록 전사. True 면 그 케이스 통과. 예외는 그대로 전파(공식도 BaseException → 실패)."""
    import numpy as np
    exact_match = out == exp
    if "are_equivalent" == entry_point:            # Mbpp/164 special oracle
        exact_match = exact_match or True
    elif "sum_div" == entry_point:                 # Mbpp/295
        exact_match = exact_match or out == 0
    elif "surface_Area" == entry_point:            # Mbpp/581
        exact_match = exact_match or abs(out - _surface_Area(*inp)) <= atol
    elif "digit_distance_nums" == entry_point:     # Mbpp/558
        exact_match = exact_match or out == _digit_distance_nums(*inp)
    elif entry_point in MBPP_OUTPUT_SET_EQ_TASKS:
        exact_match = set(out) == set(exp)
    elif entry_point in MBPP_OUTPUT_NOT_NONE_TASKS:
        if isinstance(out, bool):
            exact_match = out == exp
        else:
            exact_match = exp == (out is not None)
    atol = next_atol(atol, exp)
    if not exact_match and atol != 0:
        assert type(out) == type(exp)
        if isinstance(exp, (list, tuple)):
            assert len(out) == len(exp)
        assert np.allclose(out, exp, rtol=1e-07, atol=atol)
    else:
        assert exact_match
    return True


_LITERAL_ENV = {"__builtins__": {}, "inf": math.inf, "nan": math.nan, "Counter": Counter, "set": set}


def parse_literal(s: str):
    """스펙에 repr 로 저장된 입력·기대값 복원. 스펙은 우리가 공식 데이터에서 만든 신뢰 자료이며 후보 출력은 절대 여기로 오지 않는다."""
    return eval(s, dict(_LITERAL_ENV))  # noqa: S307


if __name__ == "__main__":
    assert mbpp_match("similar_elements", None, (5, 4), (4, 5), 0)          # 집합 비교 과제: 순서 무관
    assert mbpp_match("f", None, [1.0, 2.0000001], [1.0, 2.0], 0)           # float → atol 1e-6
    assert mbpp_match("sum_div", None, 0, 7, 0)                              # 특수 판정
    assert mbpp_match("check_str", None, "x", True, 0)                       # not-None 과제
    try:
        mbpp_match("f", None, [1, 2], (1, 2), 0); raise SystemExit("tuple/list 는 달라야 함")
    except AssertionError:
        pass
    assert next_atol(0, 1.5) == 1e-6 and next_atol(0, 1) == 0 and next_atol(1e-4, 1.5) == 1e-4
    assert atol_sequence([1, 1.5, 2, 3], 0) == [0, 0, 1e-6, 1e-6] and atol_sequence([1.5], 1e-4) == [1e-4]
    x = [(1, 2), {3}, set(), math.inf, Counter({1: 2})]
    assert parse_literal(repr(x)) == x
    print("mbppplus_compare self-check OK")
