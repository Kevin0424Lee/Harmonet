"""
harmonet/verify.py — 기계적 검증 (LLM 호출 0회)

validator 에이전트가 builder 산출물을 받아 실행하는 검증. 판정은 항상 같은 형식:

    {"passed": bool, "evidence": str, "method": [..], "cost_tokens": 0}

method 원소: "ast" (파싱·진입점 존재), "test_exec" (테스트 subprocess 실행), "apply_check" (git apply --check).
LLM은 여기서 절대 호출하지 않는다 → cost_tokens 는 항상 0. (WEEK1 A1)

task_spec 형식 (과제 씨앗 metadata["task_spec"], 피드백 씨앗이 상속):
    {"kind": "code" | "patch",
     "entry_point": str | None,        # code: 반드시 정의돼야 하는 함수명
     "tests": str | None,              # code: 실행할 *공개* 테스트 프로그램. 채점용 히든 테스트는 넣지 않는다
     "repo_dir": str, "base_commit": str}   # patch 전용
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional

_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.I | re.S)


def extract_artifact(output: str, kind: str = "code") -> str:
    """LLM 출력에서 산출물(코드 블록 / unified diff)만 뽑는다. str(output) 전체를 씨앗에 싣지 않기 위함."""
    output = output or ""
    if kind == "patch":
        from benchmark.swebench_g1 import _extract_patch  # 패치 추출·정규화 로직은 러너 것을 재사용
        return _extract_patch(output)
    blocks = _CODE_BLOCK_RE.findall(output)
    if blocks:
        return max(blocks, key=len).strip()
    m = re.search(r"(^|\n)(from\s+\S+\s+import\s+|import\s+|def\s+|class\s+)", output)
    return output[m.start():].strip() if m else output.strip()


def _artifact_evidence(artifact: str) -> str:
    """builder 산출물을 실제로 받았다는 증거: 길이 + sha256 앞 12자리 (trace에서 builder 출력과 대조 가능)."""
    return f"artifact_chars={len(artifact)} artifact_sha={hashlib.sha256(artifact.encode('utf-8')).hexdigest()[:12]}"


def verify_artifact(artifact: str, spec: Optional[Dict[str, Any]] = None, timeout_s: float = 60.0) -> Dict[str, Any]:
    spec = spec or {}
    kind = spec.get("kind", "code")
    evidence = [_artifact_evidence(artifact)]
    method = []

    if not artifact.strip():
        return {"passed": False, "evidence": "empty artifact; " + evidence[0], "method": method, "cost_tokens": 0}

    if kind == "patch":
        from benchmark.swebench_g1 import _check_patch_applies  # git worktree + apply --check (러너와 동일 판정)
        from pathlib import Path
        method.append("apply_check")
        ok, out = _check_patch_applies(Path(spec["repo_dir"]), spec["base_commit"], artifact, timeout=int(timeout_s))
        evidence.append("apply_check=" + ("ok" if ok else "fail: " + out[-300:]))
        # ponytail: 패치의 테스트 실행은 SWE-bench 하네스(Docker)가 하므로 여기서는 apply 여부까지만
        return {"passed": ok, "evidence": "; ".join(evidence), "method": method, "cost_tokens": 0}

    # ── code ──
    method.append("ast")
    try:
        tree = ast.parse(artifact)
    except SyntaxError as e:
        evidence.append(f"ast=syntax_error line {e.lineno}: {e.msg}")
        return {"passed": False, "evidence": "; ".join(evidence), "method": method, "cost_tokens": 0}
    defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    evidence.append(f"ast=ok defs={sorted(defs)[:8]}")
    entry = spec.get("entry_point")
    if entry and entry not in defs:
        evidence.append(f"entry_point={entry} missing")
        return {"passed": False, "evidence": "; ".join(evidence), "method": method, "cost_tokens": 0}

    tests = spec.get("tests")
    if tests:
        method.append("test_exec")
        with tempfile.TemporaryDirectory(prefix="harmonet_verify_") as tmp:
            path = os.path.join(tmp, "candidate_test.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(artifact + "\n\n" + tests + "\n")
            try:
                proc = subprocess.run([sys.executable, "-I", path], cwd=tmp, capture_output=True, text=True, timeout=timeout_s)
                ok = proc.returncode == 0
                evidence.append("test_exec=" + ("pass" if ok else "fail: " + (proc.stderr or proc.stdout)[-300:]))
            except subprocess.TimeoutExpired:
                ok = False
                evidence.append(f"test_exec=timeout {timeout_s}s")
        return {"passed": ok, "evidence": "; ".join(evidence), "method": method, "cost_tokens": 0}

    return {"passed": True, "evidence": "; ".join(evidence), "method": method, "cost_tokens": 0}


if __name__ == "__main__":  # 최소 자체 점검
    good = "def add(a, b):\n    return a + b\n"
    r = verify_artifact(good, {"kind": "code", "entry_point": "add", "tests": "assert add(1, 2) == 3"})
    assert r["passed"] and r["method"] == ["ast", "test_exec"] and r["cost_tokens"] == 0, r
    r = verify_artifact(good, {"kind": "code", "entry_point": "sub"})
    assert not r["passed"] and "missing" in r["evidence"], r
    r = verify_artifact("def add(a, b)\n  return", {"kind": "code"})
    assert not r["passed"] and "syntax_error" in r["evidence"], r
    r = verify_artifact(good, {"kind": "code", "entry_point": "add", "tests": "assert add(1, 2) == 4"})
    assert not r["passed"] and "test_exec=fail" in r["evidence"], r
    assert extract_artifact("text\n```python\nx = 1\n```\nmore") == "x = 1"
    print("verify.py self-check OK")
