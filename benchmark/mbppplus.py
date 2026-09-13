"""
benchmark/mbppplus.py — MBPP+ 로더 (Week2-B0). main 환경용. evalplus 는 import 하지 않는다.

스펙 파일은 benchmark/mbppplus_gt.py 가 evalplus venv 에서 공식 로직으로 만든 것(benchmark_data/mbppplus/, gitignore).
해시가 SPEC_SHA256 과 다르면 RuntimeError — 조용히 다른 스펙으로 돌지 않는다.

프롬프트 = 공식 MBPP+ prompt(설명 + assert 1개) + 코드 블록 지시. plus 케이스·정답 코드는 프롬프트·루프 어디에도 없다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SPEC_PATH = Path(__file__).resolve().parent.parent / "benchmark_data" / "mbppplus" / "MbppPlus-v0.2.0.spec.json"
SPEC_SHA256 = "b6888ff46104e154a58b5b1f2cabf08729334eecea66cad681fb90843721e5ca"   # 2026-09-14 생성 (evidence/week2/mbppplus_source.md)


@dataclass
class MbppTask:
    task_id: str
    entry_point: str
    prompt: str                       # 모델에 주는 전체 프롬프트
    tests: List[Dict[str, Any]]       # base (공개)
    hidden_tests: List[Dict[str, Any]]  # plus − base
    meta: Dict[str, Any] = field(default_factory=dict)

    def spec(self) -> Dict[str, Any]:
        return {"kind": "mbppplus", "entry_point": self.entry_point, "tests": self.tests, "hidden_tests": self.hidden_tests,
                "hidden_exposed": False}


def _build_prompt(entry_point: str, official_prompt: str) -> str:
    return (
        f"Write a Python 3 function `{entry_point}` for the task below. Return exactly one fenced ```python code block "
        "containing the complete function (and any imports) and nothing else.\n\n"
        f"{official_prompt.strip()}\n"
    )


def load_spec(path: Path = SPEC_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"MBPP+ 스펙 없음: {path}. evalplus venv 에서 `python -m benchmark.mbppplus_gt` 로 생성하라")
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    if h != SPEC_SHA256:
        raise RuntimeError(f"MBPP+ 스펙 해시 불일치: {h} != {SPEC_SHA256}. 재생성했다면 SPEC_SHA256 과 evidence 를 함께 갱신하라")
    return json.loads(path.read_text(encoding="utf-8"))


def load_mbppplus(ids: Optional[List[str]] = None) -> List[MbppTask]:
    spec = load_spec()
    tasks = []
    for tid, t in spec["tasks"].items():
        if ids is not None and tid not in ids:
            continue
        tasks.append(MbppTask(tid, t["entry_point"], _build_prompt(t["entry_point"], t["prompt"]), t["tests"], t["hidden_tests"],
                              meta={"n_plus_total": t["n_plus_total"], "n_dup_removed": t["n_dup_removed"], "atol": t["atol"]}))
    return tasks


if __name__ == "__main__":
    ts = load_mbppplus()
    print(f"tasks={len(ts)} hidden_total={sum(len(t.hidden_tests) for t in ts)}")
    t = ts[0]
    assert "canonical" not in t.prompt and all(c["input"] not in t.prompt for c in t.hidden_tests[:20])
    print(t.task_id, t.entry_point, len(t.tests), len(t.hidden_tests)); print(t.prompt)
    print("mbppplus.py self-check OK")
