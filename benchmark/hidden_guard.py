"""
benchmark/hidden_guard.py — 히든 통과율 집계 가드 (WEEK1 C3b)

히든 통과율은 채점 테스트가 프롬프트에 노출되지 않은 행에서만 의미가 있다.
MBPP 처럼 test_list 가 프롬프트에 있는 행(hidden_exposed=True)이나, 그 정보가 없는 행(옛 CSV)을
히든 통과율에 섞으면 HiddenExposedError. assert 를 쓰지 않는다 (-O 에서 사라지므로).

노출된 행은 "공개 테스트 충족률"(public_satisfaction_rate) 이라는 별도 지표로만 집계한다.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


class HiddenExposedError(ValueError):
    """히든 통과율에 노출된(또는 노출 여부 불명인) 행이 섞였다."""


def _flag(row: Any) -> Any:
    if isinstance(row, Mapping):
        return row.get("hidden_exposed", None)
    return getattr(row, "hidden_exposed", None)


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _explicit_false(v: Any) -> bool:
    """히든으로 인정하는 값은 명시적 False 뿐: bool False, 문자열 "False"/"false" (CSV). 그 외는 전부 불명으로 취급 (A0c)."""
    return v is False or (isinstance(v, str) and v in ("False", "false"))


def require_hidden(rows: Iterable[Any], where: str = "") -> None:
    """모든 행이 hidden_exposed=False 임을 요구. 필드 누락 또는 True 가 하나라도 있으면 예외."""
    for i, r in enumerate(rows):
        v = _flag(r)
        if _truthy(v):
            raise HiddenExposedError(f"{where or 'rows'}[{i}]: hidden_exposed=True — 채점 테스트가 프롬프트에 노출된 행 (MBPP 등). 공개 테스트 충족률로만 집계하라")
        if not _explicit_false(v):
            raise HiddenExposedError(f"{where or 'rows'}[{i}]: hidden_exposed={v!r} — 명시적 False 가 아니면 히든 여부 불명으로 취급한다 (누락·None·'unknown'·'0'·'' 전부 거부)")


def _passed(row: Any) -> bool:
    v = row.get("passed") if isinstance(row, Mapping) else getattr(row, "passed", False)
    return v is True or _truthy(v)


def hidden_pass_rate(rows: Sequence[Any], where: str = "") -> float:
    """히든 통과율. 가드 통과 후에만 계산."""
    rows = list(rows)
    require_hidden(rows, where)
    return sum(_passed(r) for r in rows) / len(rows) if rows else 0.0


def public_satisfaction_rate(rows: Sequence[Any]) -> float:
    """공개 테스트 충족률 — hidden_exposed=True 인 행(MBPP)의 지표. 히든 통과율과 같은 표에 두지 않는다."""
    rows = [r for r in rows if _truthy(_flag(r))]
    return sum(_passed(r) for r in rows) / len(rows) if rows else 0.0


def split_by_exposure(rows: Sequence[Any]):
    """(히든 채점 가능 행, 노출 행). 필드 누락 행은 어느 쪽에도 넣지 않고 예외."""
    hidden, exposed = [], []
    for i, r in enumerate(rows):
        v = _flag(r)
        if _truthy(v):
            exposed.append(r)
        elif _explicit_false(v):
            hidden.append(r)
        else:
            raise HiddenExposedError(f"rows[{i}]: hidden_exposed={v!r} — 명시적 True/False 가 아니면 분류하지 않는다")
    return hidden, exposed
