"""
scripts/approval.py — 실행 승인 기록 evidence/week2/APPROVAL.json 과 현재 환경의 대조 (Week2-K1). 파일 존재가 아니라 값 하나하나를 검사한다.

  {status: "approved"|"unapproved_draft", stage: "explore"|"confirm", reviewer, review_ref, freeze_commit, config_hash, policy_hash,
   feature_extractor_version, id_set_hashes{explore, confirm, reserve}, pool_gate}
탐색 승인(stage=explore): status ∧ config_hash ∧ 추출기 버전 ∧ ID 집합 해시.
확인 승인(stage=confirm): 위 + freeze_commit 이 git 이력에 존재 ∧ HEAD 가 그 후손 ∧ frozen_policy.json 해시 == policy_hash ∧ pool_gate == "진행".
하나라도 다르면 RuntimeError(ApprovalError) — 호출 0회.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
APPROVAL = ROOT / "evidence" / "week2" / "APPROVAL.json"


class ApprovalError(RuntimeError):
    pass


def id_set_hash(ids) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def id_set_hashes(cfg: dict, week2: Path = ROOT / "evidence" / "week2") -> Dict[str, str]:
    return {k: id_set_hash(json.loads((week2 / cfg["sets"][k]["file"]).read_text(encoding="utf-8"))["ids"]) for k in ("explore", "confirm", "reserve")}


def _git(*args, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def check_approval(stage: str, config_hash: str, extractor_version: str, id_hashes: Dict[str, str], frozen_path: Optional[Path] = None,
                   approval_path: Path = APPROVAL, repo: Path = ROOT) -> dict:
    if not approval_path.exists():
        raise ApprovalError(f"승인 기록이 없다: {approval_path}")
    a = json.loads(approval_path.read_text(encoding="utf-8"))
    bad = []
    if a.get("status") != "approved":
        bad.append(f"status={a.get('status')!r} (approved 아님)")
    if a.get("stage") != stage:
        bad.append(f"stage={a.get('stage')!r} != {stage!r}")
    if a.get("config_hash") != config_hash:
        bad.append(f"config_hash {str(a.get('config_hash'))[:12]} != 현재 {config_hash[:12]}")
    if a.get("feature_extractor_version") != extractor_version:
        bad.append(f"feature_extractor_version {a.get('feature_extractor_version')!r} != {extractor_version!r}")
    for k, v in id_hashes.items():
        if (a.get("id_set_hashes") or {}).get(k) != v:
            bad.append(f"id_set_hashes[{k}] 불일치")
    if stage == "confirm":
        fc = a.get("freeze_commit")
        if not fc:
            bad.append("freeze_commit 없음")
        else:
            if _git("cat-file", "-e", f"{fc}^{{commit}}", cwd=repo).returncode != 0:
                bad.append(f"freeze_commit {fc} 가 git 이력에 없다")
            elif _git("merge-base", "--is-ancestor", fc, "HEAD", cwd=repo).returncode != 0:
                bad.append(f"HEAD 가 freeze_commit {fc[:8]} 의 후손이 아니다")
        if frozen_path is None or not frozen_path.exists():
            bad.append("동결 정책 파일 없음")
        elif hashlib.sha256(frozen_path.read_bytes()).hexdigest() != a.get("policy_hash"):
            bad.append("policy_hash != frozen_policy.json 해시")
        if a.get("pool_gate") != "진행":
            bad.append(f"pool_gate={a.get('pool_gate')!r} (진행 아님)")
    if bad:
        raise ApprovalError("승인 대조 실패 — 호출 0회: " + "; ".join(bad))
    return a
