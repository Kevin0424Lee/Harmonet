"""Week2-I1: 결정 시점 특징 — pre(프롬프트) / post(decision_signals + s0 산출물). 히든·canonical 은 쓰지 않는다."""
import json
import sys
from pathlib import Path

import pytest

from benchmark.features import FEATURE_SPECS, LIB_VOCAB, error_class, post_features, pre_features, task_features

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gap_analysis as G  # noqa: E402


def test_pre_features_from_real_bcb_prompt():
    from benchmark.bcb import load_bcb
    t = load_bcb(["BigCodeBench/0"])[0]
    f = pre_features(t.prompt, t.entry_point)
    assert f["n_args"] == 1 and f["n_examples"] >= 1 and f["mentions_return"] == 1 and f["lib_random"] == 1 and f["lib_itertools"] == 1
    assert set(f) == set(FEATURE_SPECS["pre"]["num"])


def test_post_features_from_signals_shape():
    sig = {"outcome": "fail", "n_failed": 1, "diag_tail": "…\nAssertionError: 1 != 0", "artifact_chars": 120, "artifact_lines": 6,
           "build_tokens": {"prompt_tokens": 300, "completion_tokens": 200}, "build_cost_usd": 0.0013}
    f = post_features(sig, "import os\ndef task_func():\n    try:\n        return 1\n    except Exception:\n        return 0\n")
    assert f["visible"] == "fail" and f["error_class"] == "AssertionError" and f["n_functions"] == 1 and f["has_try"] == 1 and f["n_imports"] == 1
    assert error_class("RuntimeError: x") == "other" and error_class("") == "none"


def test_features_feed_p2_pre_and_post(tmp_path):
    """스펙별 설계행렬이 만들어지고 P2 가 pre / post 두 스펙으로 돈다 (합성 12과제)."""
    import numpy as np
    rng = np.random.default_rng(0)
    rows = []
    for i in range(12):
        f = pre_features(f'def task_func(a, b):\n    """\n    Returns:\n    x\n\n    Requirements:\n    - numpy\n\n    >>> task_func(1, 2)\n    3\n    """\n')
        f.update(post_features({"outcome": ["pass", "fail"][i % 2], "n_failed": i % 3, "diag_tail": "AssertionError: x" if i % 2 else "", "artifact_chars": 100 + i,
                                "artifact_lines": 5, "build_tokens": {"prompt_tokens": 300, "completion_tokens": 200 + i}, "build_cost_usd": 0.001},
                               "def task_func(a, b):\n    return a + b\n"))
        for a in G.ARMS:
            rows.append({"task_id": f"t{i}", "arm": a, "rep": 1, "hidden_pass": bool(rng.random() < 0.5), "cost_usd": 0.01, "budget_refused": False, "features": f})
    for spec in ("pre", "post"):
        r = G.policy_gain(rows, "P2", n_perm=5, n_boot=0, seed=0, with_ci=False, R=1, spec=FEATURE_SPECS[spec])
        assert "gain" in r and r["features"] == FEATURE_SPECS[spec] and abs(sum(r["pick_dist"].values()) - 1) < 1e-9
