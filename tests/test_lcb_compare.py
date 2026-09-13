"""Week2-A0: stdio 비교 규칙이 LCB 공식 testing_util.grade_stdio 와 같은 판정을 내는지 (케이스 ≥ 8)."""
import pytest

from harmonet.stdio_compare import stdio_match

CASES = [
    # (prediction, expected, 공식 판정)
    ("5\n", "5", True),                      # 후행 개행
    ("5  \n", "5\n", True),                  # 후행 공백
    ("\n\n5\n\n", "5\n", True),              # 앞뒤 빈 줄 — 전체 strip
    ("1\n\n2\n", "1\n2\n", False),           # 중간 빈 줄 → 줄 수 불일치
    ("1\n2\n", "1\n", False),                # 줄 수 불일치
    ("1.0\n", "1\n", True),                  # Decimal("1.0") == Decimal("1")
    ("-0\n", "0\n", True),                   # Decimal("-0") == Decimal("0")
    ("1e3\n", "1000\n", True),               # 지수 표기
    ("YES\n", "yes\n", False),               # 비수치 줄은 대소문자 구분
    ("12\n", "1 2\n", False),                # 줄바꿈/공백 전부 제거한 출력은 불일치 (토큰 수 다름)
    ("1 2\n", "1  2\n", True),               # 줄 안 다중 공백 — Decimal 토큰 비교로 일치
    ("abc def\n", "abc  def\n", False),      # 비수치 줄은 정확 일치만 (Decimal 변환 불가)
    ("", "", True),                          # 빈 출력 vs 빈 기대
]


@pytest.mark.parametrize("pred,exp,want", CASES)
def test_matches_official_rule(pred, exp, want):
    ok, why = stdio_match(pred, exp)
    assert ok is want, (pred, exp, why)
