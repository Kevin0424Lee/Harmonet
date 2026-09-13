"""
harmonet/stdio_compare.py — LiveCodeBench 공식 stdio 판정 규칙 (Week2-A0)

출처: LiveCodeBench/LiveCodeBench `lcb_runner/evaluation/testing_util.py` — `get_stripped_lines`,
`convert_line_to_decimals`, `grade_stdio` 의 비교 부분을 그대로 옮겼다 (main, 2026-09-13 확인).
"공백 정규화만" 으로 대체하지 않는다. 규칙:
  1. 전체 출력을 strip 한 뒤 "\\n" 으로 나누고 줄마다 strip.
  2. 줄 수가 다르면 불일치 ("mismatched output length").
  3. 줄마다: 정확히 같으면 통과. 아니면 양쪽 줄을 공백 분리 후 **모두** Decimal 로 변환할 수 있어야 하고 Decimal 리스트가 같아야 통과.
     (Decimal("1.0") == Decimal("1"), Decimal("-0") == Decimal("0"), Decimal("1e3") == Decimal("1000") 은 참. 문자열은 대소문자 구분.)
이 파일은 verify.py 의 stdio 하네스에 소스째 삽입된다 — 표준 라이브러리만 쓸 것.
"""
from decimal import Decimal, InvalidOperation
from typing import List, Tuple


def get_stripped_lines(val: str) -> List[str]:
    val = val.strip()
    return [line.strip() for line in val.split("\n")]


def convert_line_to_decimals(line: str) -> Tuple[bool, List[Decimal]]:
    try:
        return True, [Decimal(elem) for elem in line.split()]
    except (InvalidOperation, ValueError, ArithmeticError):
        return False, []


def stdio_match(prediction: str, expected: str) -> Tuple[bool, str]:
    """(일치 여부, 사유). 공식 grade_stdio 의 판정과 동일."""
    pred_lines = get_stripped_lines(prediction)
    exp_lines = get_stripped_lines(expected)
    if len(pred_lines) != len(exp_lines):
        return False, f"mismatched output length {len(pred_lines)} != {len(exp_lines)}"
    for i, (p, e) in enumerate(zip(pred_lines, exp_lines)):
        if p == e:
            continue
        ok_p, dp = convert_line_to_decimals(p)
        if not ok_p:
            return False, f"line {i}: {p[:80]!r} != {e[:80]!r}"
        ok_e, de = convert_line_to_decimals(e)
        if not ok_e:
            return False, f"line {i}: {p[:80]!r} != {e[:80]!r}"
        if dp != de:
            return False, f"line {i}: {p[:80]!r} != {e[:80]!r} (decimal)"
    return True, "ok"
