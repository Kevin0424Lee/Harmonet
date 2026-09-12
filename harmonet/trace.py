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
# 행동을 일으킨 신호. verify:visible = 공개 검증 결과 / eval:hidden = 채점기(히든 테스트) 피드백 = 누출 위험 /
# self = 에이전트 자체 결정(파이프라인 단계) / none = 무조건 실행·검증·종료
TRIGGERS = ("verify:visible", "eval:hidden", "self", "none")
TOKEN_SOURCES = ("measured", "estimated", "none")


@dataclass
class Action:
    kind: str                  # "build" | "self_revise" | "expert_review" | "verify" | "terminate"
    agent_role: str
    model: str                 # 실제 사용 모델 ID (LLM 없는 행동은 "none")
    cost: Dict[str, Any]       # 이 행동의 실측 비용 (meter_delta 형식)
    result_summary: str
    trigger: str = "none"      # TRIGGERS 중 하나
    token_source: str = "none" # cost["source"] 와 동일: measured | estimated | none(LLM 호출 없음)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"unknown action kind {self.kind!r}; expected one of {ACTION_KINDS}")
        if self.trigger not in TRIGGERS:
            raise ValueError(f"unknown trigger {self.trigger!r}; expected one of {TRIGGERS}")
        self.token_source = self.cost.get("source", "none")
        if self.token_source not in TOKEN_SOURCES:
            raise ValueError(f"unknown token_source {self.token_source!r}")


@dataclass
class TaskState:
    task_id: str
    system: str = ""                            # 어댑터 이름 (저장 경로 <run_id>/<system>/<task_id>.json)
    cost_attribution: str = "per_call"          # "per_call": 행동마다 실측 | "tick_aggregate": 틱 델타를 builder 에 귀속 (v1)
    artifact: str = ""                          # 현재 산출물 (코드/패치)
    verification: Optional[Dict] = None         # 마지막 검증 결과 (verify.verify_artifact 형식)
    leak_risk: bool = False                     # eval:hidden 트리거 행동이 하나라도 있으면 True (채점 신호가 생성에 흘러감)
    score: Optional[Dict] = None                # 사후 채점(score_hidden) 결과. trigger="post_hoc" 로만 기록되며 행동 결정에 쓰이지 않는다
    actions_after_score: int = 0                # score 가 채워진 뒤 추가된 Action 수. 0 이 아니면 save() 가 거부한다
    cost_so_far: Dict[str, Any] = field(default_factory=lambda: {
        "prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "verify_calls": 0, "source": "none"})
    history: List[Action] = field(default_factory=list)

    def record(self, kind: str, agent_role: str, model: str, cost: Dict[str, Any], summary: str,
               trigger: str = "none") -> Action:
        """행동 하나를 기록하고 누적 비용을 갱신한다."""
        act = Action(kind=kind, agent_role=agent_role, model=model, cost=dict(cost), result_summary=summary[:400],
                     trigger=trigger)
        self.history.append(act)
        if trigger == "eval:hidden":
            self.leak_risk = True
        if self.score is not None:
            self.actions_after_score += 1     # 채점 뒤의 행동 = 채점 신호가 루프로 흘렀을 가능성
        c = self.cost_so_far
        for k in ("prompt_tokens", "completion_tokens", "llm_calls", "verify_calls"):
            c[k] += int(cost.get(k, 0) or 0)
        # 하나라도 추정치면 누적도 추정치
        if cost.get("source") == "estimated" or (c["source"] == "estimated"):
            c["source"] = "estimated"
        elif cost.get("source") == "measured":
            c["source"] = "measured"
        return act

    def set_score(self, result: Dict[str, Any]) -> None:
        """에피소드 종료 후 score_hidden 결과를 기록. trigger 는 post_hoc 로 고정."""
        self.score = dict(result, trigger="post_hoc")

    def save(self, run_id: Optional[str] = None) -> Path:
        if self.actions_after_score:
            raise RuntimeError(f"[trace] score 가 기록된 뒤 Action {self.actions_after_score}개가 추가됐습니다 — "
                               "사후 채점 신호가 루프로 흘러간 실행은 저장하지 않습니다.")
        path = trace_dir(run_id) / _safe(self.system or "unknown") / f"{_safe(self.task_id)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        return path


def validate_trace(data: Dict[str, Any]) -> None:
    """저장된 trace JSON 의 스키마 검사. 어긋나면 AssertionError (테스트·스모크용)."""
    for k in ("task_id", "system", "cost_attribution", "artifact", "verification", "leak_risk", "cost_so_far", "history"):
        assert k in data, f"missing key {k}"
    assert data["cost_attribution"] in ("per_call", "tick_aggregate")
    assert isinstance(data["leak_risk"], bool)
    c = data["cost_so_far"]
    for k in ("prompt_tokens", "completion_tokens", "llm_calls", "verify_calls"):
        assert isinstance(c[k], int) and c[k] >= 0, k
    assert c["source"] in TOKEN_SOURCES
    assert data["history"], "empty history"
    for a in data["history"]:
        for k in ("kind", "agent_role", "model", "cost", "result_summary", "trigger", "token_source", "timestamp"):
            assert k in a, f"action missing {k}"
        assert a["kind"] in ACTION_KINDS and a["trigger"] in TRIGGERS and a["token_source"] in TOKEN_SOURCES
        assert a["token_source"] == a["cost"]["source"]
        if a["kind"] == "verify":
            assert a["cost"]["llm_calls"] == 0 and a["token_source"] == "none" and a["model"] == "none"
    assert data["history"][-1]["kind"] == "terminate"
    assert data["leak_risk"] == any(a["trigger"] == "eval:hidden" for a in data["history"])
    assert data.get("actions_after_score", 0) == 0
    if data.get("score") is not None:
        assert data["score"].get("trigger") == "post_hoc"


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
    validate_trace(json.loads(json.dumps(asdict(st))))
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
