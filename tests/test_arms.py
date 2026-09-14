"""Week2-D5: arm 실행기의 예산 규칙 — budget_refused(arm 개별 max_tokens 규칙, 호출 없음·계속 진행) vs budget_stop(D1 원장, 실행 중단)."""
import pytest

import benchmark.arms as A
from harmonet.budget import Budget, BudgetStop


class _Client:
    model, role, max_tokens = "claude-haiku-4-5", "builder", 4096

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        return "```python\nx = 1\n```"


def test_max_tokens_rule_refuses_below_256_without_calling():
    c = _Client()
    # 잔여 $0.001, 출력 단가 $5/M → (0.001 − 입력)/5e-6 ≈ 190 < 256 → 거부
    out, cost, usd, wall, mt, refused = A._call(c, None, "p" * 300, "s", remaining_usd=0.001, note="t")
    assert refused is True and out is None and c.calls == 0 and mt < A.MIN_MAX_TOKENS


def test_max_tokens_rule_calls_with_capped_tokens(monkeypatch):
    c = _Client()
    monkeypatch.setattr(A, "budgeted_generate", lambda client, budget, prompt, system, note="": ("```python\nx=1\n```", {"prompt_tokens": 1, "completion_tokens": 1}, 0.0, 1))
    out, cost, usd, wall, mt, refused = A._call(c, None, "p" * 300, "s", remaining_usd=0.01, note="t")
    assert refused is False and out and 256 <= mt <= 4096 and c.max_tokens == 4096   # 호출 뒤 원래 max_tokens 복원


def test_budget_stop_is_distinct_from_refused(tmp_path, monkeypatch):
    """원장 cap 초과는 BudgetStop(실행 중단) — arm 규칙의 거부(계속 진행)와 다르다."""
    import benchmark.runloop as RL
    monkeypatch.setattr(RL, "projected_cost", lambda model, chars, max_tokens: 5.0)
    b = Budget(tmp_path / "budget.json", 1.0)
    c = _Client()
    with pytest.raises(BudgetStop):
        A._call(c, b, "p" * 300, "s", remaining_usd=0.05, note="t")
    assert c.calls == 0 and b.state()["stopped_reason"] == "budget"
