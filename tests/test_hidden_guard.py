"""Week1-C3b: 히든 통과율 집계 가드. MBPP 처럼 채점 테스트가 노출된 행이나 노출 여부를 모르는 행은 히든 통과율에 들어갈 수 없다."""
import pytest

from benchmark.hidden_guard import HiddenExposedError, hidden_pass_rate, public_satisfaction_rate


def _rows(flags):
    return [{"passed": "True", "hidden_exposed": f} if f is not None else {"passed": "True"} for f in flags]


def test_exposed_row_raises():
    with pytest.raises(HiddenExposedError):
        hidden_pass_rate(_rows(["False", "True", "False"]))


def test_missing_field_raises():
    with pytest.raises(HiddenExposedError):
        hidden_pass_rate(_rows(["False", None]))


def test_all_hidden_ok_and_public_metric_is_separate():
    rows = _rows(["False", "False"]) + [{"passed": "False", "hidden_exposed": "False"}]
    assert hidden_pass_rate(rows) == pytest.approx(2 / 3)
    exposed = [{"passed": "True", "hidden_exposed": "True"}, {"passed": "False", "hidden_exposed": "True"}]
    assert public_satisfaction_rate(exposed) == pytest.approx(0.5)
    assert public_satisfaction_rate(rows) == 0.0        # 노출 행이 없으면 0 — 히든 행을 공개 지표로 세지 않는다


@pytest.mark.parametrize("bad", ["unknown", None, "0", "", 0, 1, "no"])
def test_non_explicit_values_raise(bad):
    row = {"passed": "True"} if bad is None else {"passed": "True", "hidden_exposed": bad}
    with pytest.raises(HiddenExposedError):
        hidden_pass_rate([row])


@pytest.mark.parametrize("ok", [False, "False", "false"])
def test_explicit_false_accepted(ok):
    assert hidden_pass_rate([{"passed": "True", "hidden_exposed": ok}]) == 1.0
