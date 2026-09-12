from benchmark.agents_harmonet_v2 import HarmoNetV2Adapter
from benchmark.tasks import BenchmarkTask


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate(self, prompt, system_prompt=None):
        self.calls.append((prompt, system_prompt))
        if self.outputs:
            return self.outputs.pop(0)
        return "final answer"


def test_harmonet_v2_executable_code_uses_builder_only(monkeypatch):
    fake = FakeLLM(["def add(a, b):\n    return a + b\n"])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)

    task = BenchmarkTask(
        id="he_unit_add",
        category="humaneval",
        prompt="Complete this HumanEval function. Return only Python code.\n\ndef add(a, b):",
        expected_keywords=["add"],
        complexity=2,
    )

    result = HarmoNetV2Adapter().run(task)

    assert result["metadata"]["calls"] == 1
    assert result["metadata"]["accepted_stage"] == "builder"
    assert result["metadata"]["validation"]["ok"] is True
    assert "def add" in result["output"]


def test_harmonet_v2_open_ended_keeps_validator(monkeypatch):
    fake = FakeLLM([
        "Use POST endpoints and a schema for request validation.",
        "Use POST endpoints and a schema for request validation.",
    ])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)

    task = BenchmarkTask(
        id="api_unit",
        category="api_design",
        prompt="Design an API with POST endpoints and schemas.",
        expected_keywords=["POST", "schema"],
        complexity=3,
    )

    result = HarmoNetV2Adapter().run(task)

    assert result["metadata"]["calls"] == 2
    assert result["metadata"]["stages"] == ["builder", "validator"]
    assert result["metadata"]["profile"]["validator_required"] is True


def test_harmonet_v2_repairs_invalid_executable_code(monkeypatch):
    fake = FakeLLM([
        "def add(a, b):\n    return a +\n",
        "def add(a, b):\n    return a + b\n",
    ])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)

    task = BenchmarkTask(
        id="he_unit_repair",
        category="humaneval",
        prompt="Complete this HumanEval function. Return only Python code.\n\ndef add(a, b):",
        expected_keywords=["add"],
        complexity=2,
    )

    result = HarmoNetV2Adapter().run(task)

    assert result["metadata"]["calls"] == 2
    assert result["metadata"]["accepted_stage"] == "repair"
    assert result["metadata"]["validation"]["ok"] is True


def test_harmonet_v2_exact_cache_is_opt_in(monkeypatch):
    fake = FakeLLM(["def cached(x):\n    return x\n"])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)

    task = BenchmarkTask(
        id="he_unit_cache_unique",
        category="humaneval",
        prompt="Complete this HumanEval function. Return only Python code.\n\ndef cached(x):",
        expected_keywords=["cached"],
        complexity=1,
    )
    adapter = HarmoNetV2Adapter(enable_cache=True)

    first = adapter.run(task)
    second = adapter.run(task)

    assert first["metadata"]["cache_hit"] is False
    assert second["metadata"]["cache_hit"] is True
    assert second["prompt_tokens"] == 0
    assert second["completion_tokens"] == 0
    assert len(fake.calls) == 1
