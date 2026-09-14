"""
benchmark/mock_scenario.py — 유효 코드 mock 백엔드 (Week2-F1 a). 유료 호출 0.

시나리오 파일(JSON)이 과제마다 세 변형의 **실행 가능한 코드**를 갖고, 어느 호출이 어느 변형을 내는지 지정한다:
  {"tokens": {"prompt": 1000, "completion": 700},              # 호출마다 METER 에 기록할 토큰 (measured 로 기록; 가격은 model 이름으로)
   "tasks": {"<task_id>": {"prompt": "<complete_prompt>",       # 프롬프트 매칭용
                           "variants": {"correct": "...", "wrong": "...", "near": "..."},
                           "script": {"s0": "near", "A-self": ["wrong", "correct"], "A-role": "wrong", "B-expert": "correct", "B-solo": "wrong"}}}}
호출 → 키 판별은 프롬프트·시스템 프롬프트·모델 서명으로 (실행기에 훅을 넣지 않는다):
  s0        = builder 시스템 + 원 과제 프롬프트 + 모델 A          B-solo   = builder 시스템 + 원 과제 프롬프트 + 모델 B
  A-self(×k)= builder 시스템 + 수정 프롬프트("### Task") + 모델 A   A-role   = reviewer 시스템 + 수정 프롬프트 + 모델 A
  B-expert  = reviewer 시스템 + 수정 프롬프트 + 모델 B
값이 목록이면 그 (과제, 키) 의 n번째 호출이 n번째 원소 (넘치면 마지막). 기대 히든 결과: correct→pass, wrong→fail, near→가시 pass·히든 fail.
백엔드 선택: HARMONET_LLM_BACKEND=mock-scenario, HARMONET_MOCK_SCENARIO=<json 경로>, 모델 A/B 는 HARMONET_MODEL_BUILDER/REVIEWER (가격표 이름 사용 가능).
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

from harmonet.usage import METER

BUILDER_SYSTEM_MARK = "precise Python engineer"      # benchmark.agents_single._DEFAULT_SYSTEM 의 표지
REVIEWER_SYSTEM_MARK = "senior Python reviewer"      # benchmark.arms.REVIEWER_SYSTEM 의 표지
REVISE_MARK = "### Task"                             # benchmark.arms._revise_prompt 의 표지


class ScenarioMockClient:
    def __init__(self, model: str, role_a: str, role_b: str, scenario_path: str):
        self.model = model
        self.role = "default"
        self._a, self._b = role_a, role_b
        self.sc = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
        self.calls: Counter = Counter()
        self.max_tokens = 4096

    def _side(self) -> str:
        if self.model == self._a:
            return "A"
        if self.model == self._b:
            return "B"
        raise RuntimeError(f"[mock-scenario] 모델 {self.model!r} 가 A({self._a})/B({self._b}) 어느 쪽도 아니다")

    def _key(self, prompt: str, system_prompt: Optional[str]) -> str:
        sysp = system_prompt or ""
        reviewer, revise, side = REVIEWER_SYSTEM_MARK in sysp, prompt.lstrip().startswith(REVISE_MARK), self._side()
        if reviewer and revise:
            return "A-role" if side == "A" else "B-expert"
        if revise:
            if side != "A":
                raise RuntimeError("[mock-scenario] 모델 B 의 builder 수정 호출은 시나리오에 없다")
            return "A-self"
        return "s0" if side == "A" else "B-solo"

    def _task(self, prompt: str) -> str:
        hits = [tid for tid, t in self.sc["tasks"].items() if t["prompt"].strip() and t["prompt"].strip() in prompt]
        if len(hits) != 1:
            raise RuntimeError(f"[mock-scenario] 프롬프트에서 과제를 하나로 특정하지 못함: {hits}")
        return hits[0]

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        tid, key = self._task(prompt), self._key(prompt, system_prompt)
        script = self.sc["tasks"][tid]["script"]
        if key not in script:
            raise RuntimeError(f"[mock-scenario] {tid} 시나리오에 {key!r} 가 없다")
        spec = script[key]
        n = self.calls[(tid, key)]
        self.calls[(tid, key)] += 1
        variant = spec[min(n, len(spec) - 1)] if isinstance(spec, list) else spec
        code = self.sc["tasks"][tid]["variants"][variant]
        tok = self.sc.get("tokens", {"prompt": 1000, "completion": 700})
        METER.record(tok["prompt"], tok["completion"], estimated=False, role=self.role, model=self.model)
        return f"```python\n{code}\n```"

    def count_input_tokens(self, prompt: str, system_prompt: Optional[str] = None) -> int:
        return int(self.sc.get("tokens", {"prompt": 1000})["prompt"])

    async def generate_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return self.generate(prompt, system_prompt)


def build_client(model: Optional[str]) -> ScenarioMockClient:
    path = os.getenv("HARMONET_MOCK_SCENARIO")
    if not path:
        raise RuntimeError("[mock-scenario] HARMONET_MOCK_SCENARIO=<json> 이 필요하다")
    a, b = os.getenv("HARMONET_MODEL_BUILDER"), os.getenv("HARMONET_MODEL_REVIEWER")
    if not (a and b and model):
        raise RuntimeError("[mock-scenario] HARMONET_MODEL_BUILDER / HARMONET_MODEL_REVIEWER 와 역할 모델이 있어야 한다")
    return ScenarioMockClient(model, a, b, path)


# ── 시나리오 생성 (BCB): 정답 = complete_prompt + canonical, 오답 = None 반환, 근접오답 = 처음 n_doctest 호출만 정답 ─────
def bcb_variants(task) -> Dict[str, str]:
    """near: doctest 가 부르는 횟수까지는 canonical, 그 뒤 호출은 None — 가시(doctest) pass, 히든(공식 test, 호출 ≥5) fail."""
    n_doc = max(1, task.doctest_src.count(task.entry_point + "("))
    correct = task.prompt.rstrip() + "\n" + task._canonical
    wrong = task.prompt.rstrip() + "\n    return None\n"
    near = (correct.replace(f"def {task.entry_point}(", f"def _canon_{task.entry_point}(", 1)
            + f"\n\n_ncalls = [0]\n\n\ndef {task.entry_point}(*args, **kwargs):\n    _ncalls[0] += 1\n"
            f"    if _ncalls[0] > {n_doc}:\n        return None\n    return _canon_{task.entry_point}(*args, **kwargs)\n")
    return {"correct": correct, "wrong": wrong, "near": near}


def write_bcb_scenario(task_ids, scripts: Dict[str, Dict[str, Any]], path: Path, tokens=None) -> Dict[str, Any]:
    from benchmark.bcb import load_bcb
    tasks = {}
    for t in load_bcb(list(task_ids)):
        tasks[t.task_id] = {"prompt": t.prompt, "variants": bcb_variants(t), "script": scripts[t.task_id]}
    sc = {"tokens": tokens or {"prompt": 1000, "completion": 700}, "tasks": tasks}
    path.write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    return sc
