"""
harmonet/trace.py — 실행 추적 (WEEK1 A4)

모든 어댑터는 과제 하나를 돌릴 때 TaskState 를 만들고, 행동마다 Action 을 추가하고, 끝나면 JSON 으로 저장한다.
2주차 실험("같은 작업 상태에서 종료 / 자기 수정 / 전문가 추가")의 비교 단위가 이 객체다.

비용은 반드시 METER 실측. 추정치가 섞이면 Action.cost["source"] == "estimated".
저장 위치: evidence/traces/<run_id>/<system>/<task_id>.json
    run_id  ← HARMONET_TRACE_RUN_ID (없으면 프로세스마다 시각+pid 로 한 번 생성)
    디렉토리 ← HARMONET_TRACE_DIR (기본 evidence/traces)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .usage import METER

ACTION_KINDS = ("build", "self_revise", "expert_review", "verify", "terminate")


@dataclass
class Action:
    kind: str                  # "build" | "self_revise" | "expert_review" | "verify" | "terminate"
    agent_role: str
    model: str                 # 실제 사용 모델 ID (LLM 없는 행동은 "none")
    cost: Dict[str, Any]       # 이 행동의 실측 비용 (meter_delta 형식)
    result_summary: str
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"unknown action kind {self.kind!r}; expected one of {ACTION_KINDS}")


@dataclass
class TaskState:
    task_id: str
    system: str = ""                            # 어댑터 이름 (저장 경로 <run_id>/<system>/<task_id>.json)
    cost_attribution: str = "per_call"          # "per_call": 행동마다 실측 | "tick_aggregate": 틱 델타를 builder 에 귀속 (v1)
    artifact: str = ""                          # 현재 산출물 (코드/패치)
    verification: Optional[Dict] = None         # 마지막 검증 결과 (verify.verify_artifact 형식)
    cost_so_far: Dict[str, Any] = field(default_factory=lambda: {
        "prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "verify_calls": 0, "source": "none"})
    history: List[Action] = field(default_factory=list)

    def record(self, kind: str, agent_role: str, model: str, cost: Dict[str, Any], summary: str) -> Action:
        """행동 하나를 기록하고 누적 비용을 갱신한다."""
        act = Action(kind=kind, agent_role=agent_role, model=model, cost=dict(cost), result_summary=summary[:400])
        self.history.append(act)
        c = self.cost_so_far
        for k in ("prompt_tokens", "completion_tokens", "llm_calls", "verify_calls"):
            c[k] += int(cost.get(k, 0) or 0)
        # 하나라도 추정치면 누적도 추정치
        if cost.get("source") == "estimated" or (c["source"] == "estimated"):
            c["source"] = "estimated"
        elif cost.get("source") == "measured":
            c["source"] = "measured"
        return act

    def save(self, run_id: Optional[str] = None) -> Path:
        path = trace_dir(run_id) / _safe(self.system or "unknown") / f"{_safe(self.task_id)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        return path


# ── 비용 측정 도우미 ──────────────────────────────────────────────────

def meter_delta(before: Dict[str, int], after: Optional[Dict[str, int]] = None, verify_calls: int = 0) -> Dict[str, Any]:
    """METER.snapshot() 두 시점의 차이를 Action.cost 형식으로. LLM 호출이 없으면 source='none'."""
    after = after or METER.snapshot()
    calls = after["calls"] - before["calls"]
    est = after["estimated_calls"] - before["estimated_calls"]
    return {
        "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
        "completion_tokens": after["completion_tokens"] - before["completion_tokens"],
        "llm_calls": calls,
        "verify_calls": verify_calls,
        "source": "none" if calls == 0 else ("estimated" if est > 0 else "measured"),
    }


NO_COST = {"prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "verify_calls": 0, "source": "none"}


def model_id(client: Any) -> str:
    """클라이언트가 실제로 쓰는 모델 ID. Mock 은 설정된 이름(기본 'mock')."""
    return str(getattr(client, "model", None) or type(client).__name__.replace("Client", "").lower())


def model_used(role: str, client: Any) -> str:
    """역할이 마지막 호출에서 실제로 쓴 모델: response.model 우선, 없으면 설정 문자열."""
    return METER.snapshot(role).get("last_model") or model_id(client)


# ── run_id / 저장 경로 ────────────────────────────────────────────────
_DEFAULT_RUN_ID: Optional[str] = None


def run_id() -> str:
    global _DEFAULT_RUN_ID
    env = os.getenv("HARMONET_TRACE_RUN_ID")
    if env:
        return env
    if _DEFAULT_RUN_ID is None:
        _DEFAULT_RUN_ID = time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"
    return _DEFAULT_RUN_ID


def trace_dir(rid: Optional[str] = None) -> Path:
    return Path(os.getenv("HARMONET_TRACE_DIR", "evidence/traces")) / (rid or run_id())


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)


if __name__ == "__main__":  # 최소 자체 점검
    import tempfile
    os.environ["HARMONET_TRACE_DIR"] = tempfile.mkdtemp()
    METER.reset()
    st = TaskState("t/1")
    b = METER.snapshot()
    METER.record(10, 5, estimated=False)
    st.record("build", "builder", "m", meter_delta(b), "ok")
    st.record("verify", "validator", "none", dict(NO_COST, verify_calls=1), "ast ok")
    st.record("terminate", "system", "none", NO_COST, "done")
    assert st.cost_so_far == {"prompt_tokens": 10, "completion_tokens": 5, "llm_calls": 1, "verify_calls": 1, "source": "measured"}, st.cost_so_far
    p = st.save("selfcheck")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["task_id"] == "t/1" and len(data["history"]) == 3 and p.name == "t_1.json" and p.parent.name == "unknown"
    try:
        st.record("bogus", "x", "m", NO_COST, "")
        raise SystemExit("bad kind accepted")
    except ValueError:
        pass
    print("trace.py self-check OK", p)
