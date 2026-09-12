import time

import numpy as np

from benchmark.agents_harmonet_v2 import HarmoNetV2Adapter
from benchmark.tasks import BenchmarkTask
from harmonet.field import DataUniverseField, Seed
from harmonet.resonance import KuraMotoCoupler, ResonanceDetector


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate(self, prompt, system_prompt=None):
        self.calls.append((prompt, system_prompt))
        if self.outputs:
            return self.outputs.pop(0)
        return "final answer"


def _unit(seed: int, dim: int = 16) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=dim).astype(np.float32)
    return vec / (np.linalg.norm(vec) + 1e-8)


def _seed(seed_id: str, creator: str, freq: np.ndarray, energy: float = 0.8) -> Seed:
    return Seed(
        id=seed_id,
        creator_id=creator,
        frequency=freq,
        payload=freq.copy(),
        rule_description=f"G2 integration seed {seed_id}",
        energy=energy,
        phase=0.2,
        ttl_seconds=300,
    )


def _code_task(task_id: str, entry: str, prompt: str) -> BenchmarkTask:
    return BenchmarkTask(
        id=task_id,
        category="humaneval",
        prompt=f"Return only Python code. Define `{entry}`.\n\n{prompt}",
        expected_keywords=[entry],
        complexity=2,
    )


def _exec_function(code: str, name: str, *args):
    namespace = {}
    exec(code, namespace)
    return namespace[name](*args)


EXECUTABLE_SCENARIOS = [
    ("g2_exec_add", "add", "def add(a, b):\n    return a + b\n", (2, 5), 7),
    ("g2_exec_mul", "mul", "def mul(a, b):\n    return a * b\n", (3, 4), 12),
    ("g2_exec_reverse", "reverse_text", "def reverse_text(s):\n    return s[::-1]\n", ("abc",), "cba"),
    ("g2_exec_even", "is_even", "def is_even(n):\n    return n % 2 == 0\n", (8,), True),
    ("g2_exec_max", "max2", "def max2(a, b):\n    return a if a >= b else b\n", (4, 9), 9),
    ("g2_exec_len", "size", "def size(xs):\n    return len(xs)\n", ([1, 2, 3],), 3),
    ("g2_exec_first", "first", "def first(xs):\n    return xs[0]\n", ([9, 8],), 9),
    ("g2_exec_abs", "abs_diff", "def abs_diff(a, b):\n    return abs(a - b)\n", (3, 10), 7),
    ("g2_exec_upper", "upper", "def upper(s):\n    return s.upper()\n", ("ab",), "AB"),
    ("g2_exec_sum", "sum_list", "def sum_list(xs):\n    return sum(xs)\n", ([1, 2, 3],), 6),
    ("g2_exec_pal", "is_pal", "def is_pal(s):\n    return s == s[::-1]\n", ("level",), True),
    ("g2_exec_min", "min2", "def min2(a, b):\n    return a if a <= b else b\n", (4, 9), 4),
]


def test_g2_executable_builder_path(monkeypatch, scenario):
    task_id, entry, code, args, expected = scenario
    fake = FakeLLM([code])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)

    result = HarmoNetV2Adapter().run(_code_task(task_id, entry, code))

    assert result["metadata"]["accepted_stage"] == "builder"
    assert result["metadata"]["calls"] == 1
    assert _exec_function(result["output"], entry, *args) == expected


test_g2_executable_builder_path = __import__("pytest").mark.parametrize(
    "scenario", EXECUTABLE_SCENARIOS
)(test_g2_executable_builder_path)


REPAIR_SCENARIOS = [
    ("g2_repair_add", "add", "def add(a, b):\n    return a +\n", "def add(a, b):\n    return a + b\n"),
    ("g2_repair_mul", "mul", "def mul(a, b):\n    return a *\n", "def mul(a, b):\n    return a * b\n"),
    ("g2_repair_square", "square", "def square(x):\n    return x **\n", "def square(x):\n    return x * x\n"),
    ("g2_repair_neg", "negate", "def negate(x):\n    return -\n", "def negate(x):\n    return -x\n"),
    ("g2_repair_inc", "inc", "def inc(x):\n    return x +\n", "def inc(x):\n    return x + 1\n"),
    ("g2_repair_dec", "dec", "def dec(x):\n    return x -\n", "def dec(x):\n    return x - 1\n"),
    ("g2_repair_empty", "identity", "", "def identity(x):\n    return x\n"),
    ("g2_repair_missing", "target", "def other(x):\n    return x\n", "def target(x):\n    return x\n"),
]


def test_g2_static_repair_path(monkeypatch, scenario):
    task_id, entry, bad, fixed = scenario
    fake = FakeLLM([bad, fixed])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)

    result = HarmoNetV2Adapter().run(_code_task(task_id, entry, fixed))

    assert result["metadata"]["accepted_stage"] == "repair"
    assert result["metadata"]["validation"]["ok"] is True
    assert f"def {entry}" in result["output"]


test_g2_static_repair_path = __import__("pytest").mark.parametrize(
    "scenario", REPAIR_SCENARIOS
)(test_g2_static_repair_path)


EVAL_REPAIR_SCENARIOS = [
    ("g2_eval_rot", "find_Rotations", "def find_Rotations(s):\n    return 1\n", "def find_Rotations(s):\n    return next(i for i in range(1, len(s)+1) if s[i:]+s[:i] == s)\n"),
    ("g2_eval_distinct", "count_distinct_characters", "def count_distinct_characters(s):\n    return len(set(s))\n", "def count_distinct_characters(s):\n    return len(set(s.lower()))\n"),
    ("g2_eval_factorial", "fact", "def fact(n):\n    return n\n", "def fact(n):\n    return 1 if n <= 1 else n * fact(n-1)\n"),
    ("g2_eval_fib", "fib", "def fib(n):\n    return n\n", "def fib(n):\n    a,b=0,1\n    for _ in range(n):\n        a,b=b,a+b\n    return a\n"),
    ("g2_eval_sort", "sort_nums", "def sort_nums(xs):\n    return xs\n", "def sort_nums(xs):\n    return sorted(xs)\n"),
    ("g2_eval_unique", "unique", "def unique(xs):\n    return xs\n", "def unique(xs):\n    return list(dict.fromkeys(xs))\n"),
]


def test_g2_evaluator_aware_repair_path(monkeypatch, scenario):
    task_id, entry, bad, fixed = scenario
    fake = FakeLLM([fixed])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)
    adapter = HarmoNetV2Adapter()
    task = _code_task(task_id, entry, fixed)

    result = adapter.repair_after_eval(task, bad, "AssertionError")

    assert result["metadata"]["eval_repair_attempted"] is True
    assert result["metadata"]["eval_repair_static_ok"] is True
    assert f"def {entry}" in result["output"]


test_g2_evaluator_aware_repair_path = __import__("pytest").mark.parametrize(
    "scenario", EVAL_REPAIR_SCENARIOS
)(test_g2_evaluator_aware_repair_path)


OPEN_ENDED_SCENARIOS = [
    ("g2_open_api", "Design POST API with schema validation.", ["POST", "schema"]),
    ("g2_open_cache", "Design cache invalidation with TTL.", ["cache", "TTL"]),
    ("g2_open_obs", "Design logs and metrics.", ["logs", "metrics"]),
    ("g2_open_retry", "Design retry with circuit breaker.", ["retry", "circuit"]),
    ("g2_open_queue", "Design queue backpressure.", ["queue", "backpressure"]),
    ("g2_open_auth", "Design JWT auth with refresh tokens.", ["JWT", "refresh"]),
    ("g2_open_trace", "Design tracing with correlation IDs.", ["tracing", "correlation"]),
    ("g2_open_dlq", "Design dead letter queue handling.", ["dead", "queue"]),
]


def test_g2_open_ended_uses_validator(monkeypatch, scenario):
    task_id, prompt, keywords = scenario
    answer = " ".join(keywords) + " final design"
    fake = FakeLLM([answer, answer])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)
    task = BenchmarkTask(task_id, "architecture", prompt, keywords, complexity=3)

    result = HarmoNetV2Adapter().run(task)

    assert result["metadata"]["stages"] == ["builder", "validator"]
    assert result["metadata"]["validation"]["ok"] is True


test_g2_open_ended_uses_validator = __import__("pytest").mark.parametrize(
    "scenario", OPEN_ENDED_SCENARIOS
)(test_g2_open_ended_uses_validator)


CACHE_SCENARIOS = [
    ("g2_cache_a", "cached_a"),
    ("g2_cache_b", "cached_b"),
    ("g2_cache_c", "cached_c"),
    ("g2_cache_d", "cached_d"),
    ("g2_cache_e", "cached_e"),
    ("g2_cache_f", "cached_f"),
]


def test_g2_cache_is_exact_and_opt_in(monkeypatch, scenario):
    task_id, entry = scenario
    fake = FakeLLM([f"def {entry}(x):\n    return x\n"])
    monkeypatch.setattr("benchmark.agents_harmonet_v2.get_llm_client", lambda role=None: fake)
    adapter = HarmoNetV2Adapter(enable_cache=True)
    task = _code_task(task_id, entry, f"def {entry}(x):")

    first = adapter.run(task)
    second = adapter.run(task)

    assert first["metadata"]["cache_hit"] is False
    assert second["metadata"]["cache_hit"] is True
    assert len(fake.calls) == 1


test_g2_cache_is_exact_and_opt_in = __import__("pytest").mark.parametrize(
    "scenario", CACHE_SCENARIOS
)(test_g2_cache_is_exact_and_opt_in)


FIELD_SCENARIOS = [
    ("claim_once", 8, 6),
    ("ttl_evict", 8, 4),
    ("propagate_energy", 8, 5),
    ("multi_seed_density", 16, 12),
    ("duplicate_claims", 8, 7),
]


def test_g2_field_store_integration(scenario):
    mode, grid, count = scenario
    universe = DataUniverseField(dim=16, grid_size=grid)
    freq = _unit(100)
    for i in range(count):
        universe.deposit_seed(_seed(f"{mode}-{i}", f"creator-{i}", freq), i % grid)

    if mode == "claim_once":
        assert universe.claim_seed(f"{mode}-0", "agent-a") is True
        assert universe.claim_seed(f"{mode}-0", "agent-b") is False
    elif mode == "ttl_evict":
        expired = _seed("expired-g2", "creator", freq)
        expired.timestamp = time.time() - 1000
        expired.ttl_seconds = 1
        universe.seed_registry[expired.id] = (0, expired)
        assert universe.evict_expired_seeds() >= 1
        assert expired.id not in universe.seed_registry
    elif mode == "propagate_energy":
        before = universe.get_global_energy()
        universe.propagate(dt=0.2)
        assert universe.get_global_energy() <= before * 1.5
    elif mode == "multi_seed_density":
        assert len(universe.seed_registry) == count
        assert universe.get_global_energy() > 0
    elif mode == "duplicate_claims":
        wins = [universe.claim_seed(f"{mode}-1", f"agent-{i}") for i in range(5)]
        assert wins.count(True) == 1


test_g2_field_store_integration = __import__("pytest").mark.parametrize(
    "scenario", FIELD_SCENARIOS
)(test_g2_field_store_integration)


RESONANCE_SCENARIOS = [
    ("scan_detects", 0.0),
    ("scan_filters", 0.99),
    ("own_seed_skip", 0.0),
    ("kuramoto_step", 0.0),
    ("order_parameter", 0.0),
]


def test_g2_resonance_integration(scenario):
    mode, threshold = scenario
    universe = DataUniverseField(dim=16, grid_size=8)
    freq = _unit(200)
    detector = ResonanceDetector("agent-x", freq, resonance_threshold=threshold)

    if mode == "scan_detects":
        universe.deposit_seed(_seed("res-a", "other", freq), 3)
        assert detector.scan_field(universe, 3, 4)
    elif mode == "scan_filters":
        universe.deposit_seed(_seed("res-b", "other", _unit(201)), 3)
        assert detector.scan_field(universe, 3, 4) == []
    elif mode == "own_seed_skip":
        universe.deposit_seed(_seed("res-c", "agent-x", freq), 3)
        assert detector.scan_field(universe, 3, 4) == []
    elif mode == "kuramoto_step":
        kc = KuraMotoCoupler(coupling_strength=0.5)
        kc.register_agent("a", 1.0)
        kc.register_agent("b", 1.3)
        before = dict(kc.phases)
        kc.step(dt=0.1)
        assert kc.phases != before
    elif mode == "order_parameter":
        kc = KuraMotoCoupler(coupling_strength=0.5)
        for i in range(5):
            kc.register_agent(f"a{i}", float(i))
        r, _ = kc.get_order_parameter()
        assert 0.0 <= r <= 1.0


test_g2_resonance_integration = __import__("pytest").mark.parametrize(
    "scenario", RESONANCE_SCENARIOS
)(test_g2_resonance_integration)
