"""
benchmark/features.py — 정책 학습용 결정 시점 특징 (Week2-I1, 사전 등록). 모델에 노출되지 않는 정보(히든 테스트·canonical)는 쓰지 않는다.

실행 전 특징 pre (과제 프롬프트 = BCB complete_prompt 만으로 계산):
  prompt_chars, n_examples(docstring 의 `>>>` 수), lib_<name>(Requirements 라이브러리 원-핫: 적격 풀 빈도 상위 12 + lib_other), n_args(entry_point 인자 수, ast),
  mentions_return(docstring 에 "Returns:" 절 존재)
실행 후 특징 post (§8 decision_signals.json 에서 계산):
  visible(outcome 범주), n_failed, error_class(예외 이름: 상위 8 + other; evidence 꼬리에서 `XxxError:` 패턴), artifact_chars, artifact_lines,
  n_functions / has_try / n_imports (s0 산출물 AST), s0_prompt_tokens, s0_completion_tokens, s0_cost_usd
P2 설정(고정): 표준화, L2 λ = 1.0 (H3 합성과 동일), IRLS 8, K=5, R=20, 특징 순열 2000, 과제 부트스트랩 1000.
부차 분석: P2-pre(pre 만) / P2-post(pre+post). P1(visible 조회표)은 진단.
"""
from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Sequence

LIB_VOCAB = ("pandas", "numpy", "matplotlib", "random", "sklearn", "collections", "re", "itertools", "scipy", "string", "os", "math")   # 적격 403 빈도 상위 12
ERROR_VOCAB = ("AssertionError", "TypeError", "ValueError", "AttributeError", "KeyError", "NameError", "ImportError", "IndexError")  # 상위 8 + other
P2_CONFIG = {"standardize": True, "l2_lambda": 1.0, "irls_iters": 8, "cv_k": 5, "cv_r": 20, "n_perm": 2000, "n_boot": 1000}

PRE_NUM = ("prompt_chars", "n_examples", "n_args", "mentions_return") + tuple(f"lib_{l}" for l in LIB_VOCAB) + ("lib_other",)
PRE_CAT: tuple = ()
POST_NUM = ("n_failed", "artifact_chars", "artifact_lines", "n_functions", "has_try", "n_imports", "s0_prompt_tokens", "s0_completion_tokens", "s0_cost_usd")
POST_CAT = ("visible", "error_class")
FEATURE_SPECS = {"pre": {"num": list(PRE_NUM), "cat": list(PRE_CAT)}, "post": {"num": list(PRE_NUM + POST_NUM), "cat": list(PRE_CAT + POST_CAT)}}

_ERR_RE = re.compile(r"\b([A-Za-z_]*(?:Error|Exception|Exit|Interrupt|Warning))\b")


def _requirements(prompt: str) -> List[str]:
    m = re.search(r"Requirements:\s*\n((?:\s*-\s*.+\n?)+)", prompt)
    if not m:
        return []
    return [ln.strip().lstrip("-").strip().split(".")[0].split()[0] for ln in m.group(1).splitlines() if ln.strip().startswith("-")]


def pre_features(prompt: str, entry_point: str = "task_func") -> Dict[str, Any]:
    libs = set(_requirements(prompt))
    n_args = 0
    try:
        for node in ast.walk(ast.parse(prompt)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point:
                a = node.args
                n_args = len(a.args) + len(a.kwonlyargs) + (1 if a.vararg else 0) + (1 if a.kwarg else 0)
                break
    except SyntaxError:
        n_args = -1                                        # 서명 파싱 실패도 특징 (조용히 0 으로 두지 않는다)
    f = {"prompt_chars": len(prompt), "n_examples": prompt.count(">>>"), "n_args": n_args, "mentions_return": int("Returns:" in prompt),
         "lib_other": int(any(l not in LIB_VOCAB for l in libs))}
    for l in LIB_VOCAB:
        f[f"lib_{l}"] = int(l in libs)
    return f


def ast_features(code: str) -> Dict[str, Any]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"n_functions": 0, "has_try": 0, "n_imports": 0, "ast_ok": 0}
    return {"n_functions": sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)),
            "has_try": int(any(isinstance(n, ast.Try) for n in ast.walk(tree))),
            "n_imports": sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree)), "ast_ok": 1}


def error_class(evidence_tail: str) -> str:
    """evidence 꼬리에서 마지막 예외 이름. 없으면 'none', 어휘 밖이면 'other'."""
    names = _ERR_RE.findall(evidence_tail or "")
    if not names:
        return "none"
    n = names[-1]
    return n if n in ERROR_VOCAB else "other"


def post_features(signals: Dict[str, Any], artifact_code: str) -> Dict[str, Any]:
    """§8 decision_signals.json + s0 산출물 → post 특징. signals 는 arms.make_s0 가 쓴 것."""
    f = {"visible": str(signals["outcome"]), "n_failed": int(signals["n_failed"]), "error_class": error_class(signals.get("diag_tail", "")),
         "artifact_chars": int(signals["artifact_chars"]), "artifact_lines": int(signals["artifact_lines"]),
         "s0_prompt_tokens": int(signals["build_tokens"]["prompt_tokens"]), "s0_completion_tokens": int(signals["build_tokens"]["completion_tokens"]),
         "s0_cost_usd": float(signals["build_cost_usd"] if signals["build_cost_usd"] is not None else -1.0)}
    f.update({k: v for k, v in ast_features(artifact_code).items() if k != "ast_ok"})
    return f


def task_features(prompt: str, signals: Dict[str, Any], artifact_code: str, entry_point: str = "task_func") -> Dict[str, Any]:
    return {**pre_features(prompt, entry_point), **post_features(signals, artifact_code)}


if __name__ == "__main__":
    p = 'import numpy as np\n\ndef task_func(a, b, c=1):\n    """\n    Do X.\n\n    Returns:\n    float\n\n    Requirements:\n    - numpy\n    - foo.bar\n\n    Example:\n    >>> task_func(1, 2)\n    3\n    """\n'
    f = pre_features(p)
    assert f["n_args"] == 3 and f["n_examples"] == 1 and f["lib_numpy"] == 1 and f["lib_other"] == 1 and f["mentions_return"] == 1
    assert error_class("... AssertionError: 1 != 2") == "AssertionError" and error_class("boom ZeroDivisionError: x") == "other" and error_class("") == "none"
    assert ast_features("import os\ndef f():\n    try:\n        pass\n    except Exception:\n        pass\n") == {"n_functions": 1, "has_try": 1, "n_imports": 1, "ast_ok": 1}
    print("features.py self-check OK")
