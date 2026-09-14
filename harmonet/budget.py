"""
harmonet/budget.py — 누적 예산 원장 (Week2-D1 ①)

원장 파일 evidence/week2/<budget_id>/budget.json:
    {"cap": 사전 등록 상한(USD), "spent": 실측 누적, "reserved": 진행 중 호출의 예약액, "n_calls", "stopped_reason": null|"budget"|"unpriced"|…, "log": [...]}
A·B 가 별도 프로세스로 같은 원장을 쓰므로 읽기-수정-쓰기는 파일 잠금(Windows msvcrt.locking / POSIX fcntl.flock) 아래서만 한다.

호출 전  reserve(projected):  projected = 입력 추정비용 + max_tokens × 출력단가.  spent + reserved + projected > cap → 예약 거부(False),
                             stopped_reason="budget" 기록. 호출자는 호출하지 않고 부분 결과를 저장한 뒤 종료 코드 ≠ 0 으로 끝낸다.
                             예약을 먼저 잡기 때문에 두 프로세스가 동시에 검사해도 합계가 cap 을 넘지 않는다.
호출 후  commit(projected, actual): 예약 해제 + 실측 가산. actual 이 None(미측정)이면 stopped_reason="unpriced" (다음 호출 금지, B2 규칙).

입력 토큰 추정은 chars/3 (실측보다 크게 잡아 먼저 멈추는 쪽으로 보수적). 출력은 max_tokens 전부로 가정.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from harmonet.pricing import price_for

_IS_WIN = os.name == "nt"


class BudgetStop(RuntimeError):
    """예산 상한으로 호출을 하지 않음 (또는 원장이 이미 stopped)."""


class _Locked:
    """원장 옆 .lock 파일에 배타 잠금. with 블록 안에서만 원장을 읽고 쓴다."""

    def __init__(self, path: Path):
        self.lock_path = path.with_suffix(".lock")
        self.fh = None

    def __enter__(self):
        self.fh = open(self.lock_path, "a+")
        if _IS_WIN:
            import msvcrt
            while True:                                   # msvcrt.locking(LK_LOCK) 은 10회 재시도 뒤 예외 → 무한 대기로 감싼다
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1); break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if _IS_WIN:
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()


class Budget:
    def __init__(self, path: Path, cap: float):
        self.path = Path(path)
        self.cap = float(cap)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _Locked(self.path):
            d = self._read()
            if d is None:
                self._write({"cap": self.cap, "spent": 0.0, "reserved": 0.0, "n_calls": 0, "stopped_reason": None, "log": [],
                             "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
            elif abs(d["cap"] - self.cap) > 1e-9:
                raise RuntimeError(f"[budget] 원장 cap {d['cap']} ≠ 요청 cap {self.cap} ({self.path}) — 사전 등록값과 다르면 새 원장을 써라")

    # ── 파일 I/O (잠금 안에서만) ──
    def _read(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, d: Dict[str, Any]) -> None:
        d["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ── 공개 API ──
    def state(self) -> Dict[str, Any]:
        with _Locked(self.path):
            return self._read()

    def reserve(self, projected: float, note: str = "") -> bool:
        with _Locked(self.path):
            d = self._read()
            if d["stopped_reason"]:
                return False
            if d["spent"] + d["reserved"] + projected > d["cap"] + 1e-12:
                d["stopped_reason"] = "budget"
                d["log"].append({"t": time.time(), "event": "refuse", "projected": projected, "spent": d["spent"], "reserved": d["reserved"], "note": note})
                self._write(d)
                return False
            d["reserved"] = round(d["reserved"] + projected, 10)
            self._write(d)
            return True

    def commit(self, projected: float, actual: Optional[float], note: str = "") -> None:
        with _Locked(self.path):
            d = self._read()
            d["reserved"] = max(0.0, round(d["reserved"] - projected, 10))
            d["n_calls"] += 1
            if actual is None:
                d["stopped_reason"] = d["stopped_reason"] or "unpriced"
            else:
                d["spent"] = round(d["spent"] + actual, 10)
            d["log"].append({"t": time.time(), "event": "commit", "projected": projected, "actual": actual, "note": note})
            self._write(d)

    def stop(self, reason: str) -> None:
        with _Locked(self.path):
            d = self._read()
            d["stopped_reason"] = d["stopped_reason"] or reason
            self._write(d)


def projected_cost(model: Optional[str], prompt_chars: int, max_tokens: int) -> float:
    """호출 전 상한 추정: 입력 chars/3 토큰 × 입력단가 + max_tokens × 출력단가. 가격 미상이면 RuntimeError (사전 점검이 먼저 막지만 이중 확인)."""
    entry, sid = price_for(model)
    if entry is None:
        raise RuntimeError(f"[budget] 모델 {model!r} 가격이 {sid} 에 없어 예산을 추정할 수 없다")
    return (prompt_chars / 3.0) * entry["input"] / 1e6 + max_tokens * entry["output"] / 1e6


def budget_from_env(default_id: Optional[str] = None) -> Optional[Budget]:
    """HARMONET_BUDGET_CAP(USD) 가 있으면 evidence/week2/<HARMONET_BUDGET_ID or default_id>/budget.json 원장. 없으면 None (호출자가 유료 백엔드면 거부)."""
    cap = os.getenv("HARMONET_BUDGET_CAP")
    if not cap:
        return None
    bid = os.getenv("HARMONET_BUDGET_ID") or default_id
    if not bid:
        raise RuntimeError("[budget] HARMONET_BUDGET_CAP 이 있으면 HARMONET_BUDGET_ID(또는 run_id) 도 있어야 한다")
    root = Path(os.getenv("HARMONET_BUDGET_ROOT") or (Path(__file__).resolve().parent.parent / "evidence" / "week2"))
    return Budget(root / bid / "budget.json", float(cap))


if __name__ == "__main__":
    import tempfile
    p = Path(tempfile.mkdtemp()) / "budget.json"
    b = Budget(p, 1.0)
    assert b.reserve(0.6) and not b.reserve(0.6) and b.state()["stopped_reason"] == "budget"
    b2 = Budget(p, 1.0); b2.commit(0.6, 0.55); assert b2.state()["spent"] == 0.55 and b2.state()["reserved"] == 0.0
    assert projected_cost("claude-haiku-4-5", 3000, 1000) == (1000 * 1.0 + 1000 * 5.0) / 1e6
    print("budget.py self-check OK")
