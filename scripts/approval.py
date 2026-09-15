"""
scripts/approval.py — 실행 승인 기록 evidence/week2/APPROVAL.json 과 현재 환경의 대조 (Week2-K1 → L2). 파일 존재가 아니라 값 하나하나를 검사한다.

  {status: "approved"|"unapproved_draft", stage: "explore"|"confirm", reviewer, review_ref, freeze_commit, config_hash, policy_hash,
   feature_extractor_version, id_set_hashes{explore, confirm, reserve}, pool_gate, scope_files{path: sha256}}
공통: status ∧ stage ∧ reviewer/review_ref 비어 있지 않음 ∧ config_hash ∧ 추출기 버전 ∧ ID 집합 해시 ∧ **검증 범위 파일 해시**(SCOPE, 승인 후 실행 관련 변경 탐지).
확인(stage=confirm): 위 + freeze_commit 이 git 이력에 존재 ∧ HEAD 후손 ∧ **그 커밋에 동결 산출물이 들어 있고 blob == 현재 파일** ∧ policy_hash ∧
  frozen_policy.json 내부(config_sha256·features_version·explore_ids·n_explore·pool_gate) 가 실제 설정·ID 파일·승인 기록과 일치 ∧
  pool_gate 는 문자열만이 아니라 동결된 관문 수치·등록 문턱·판정의 일관성까지.
하나라도 다르면 ApprovalError(RuntimeError) — 호출 0회. `python scripts/approval.py --scope` 는 현재 범위 해시를 출력한다(승인 작성용).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
APPROVAL = ROOT / "evidence" / "week2" / "APPROVAL.json"
# 검증 범위 (L2-4): 실행에 영향을 주는 코드·설정·ID 파일. 문서(docs/, *.md)는 넣지 않는다.
SCOPE: List[str] = [
    "benchmark/arms.py", "benchmark/runloop.py", "benchmark/s0_import.py", "benchmark/features.py", "benchmark/bcb.py", "benchmark/bcb_eligibility.py",
    "benchmark/mock_scenario.py", "benchmark/agents_single.py", "harmonet/budget.py", "harmonet/llm.py", "harmonet/verify.py", "harmonet/bcb_check.py", "harmonet/bcb_harness.py",
    "harmonet/pricing.py", "harmonet/trace.py", "harmonet/usage.py", "scripts/gap_analysis.py", "scripts/pilot_dryrun.py", "scripts/approval.py",
    "scripts/prereg_render.py", "evidence/week2/pilot_config_v4.json", "evidence/week2/pilot_explore_ids_bcb.json", "evidence/week2/pilot_confirm_ids_bcb.json",
    "evidence/week2/pilot_reserve_ids_bcb.json", "evidence/week2/pool_probe_bcb_A.json", "evidence/week2/bcb_eligibility.json",
]


class ApprovalError(RuntimeError):
    pass


def id_set_hash(ids) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def id_set_hashes(cfg: dict, week2: Path = ROOT / "evidence" / "week2") -> Dict[str, str]:
    return {k: id_set_hash(json.loads((week2 / cfg["sets"][k]["file"]).read_text(encoding="utf-8"))["ids"]) for k in ("explore", "confirm", "reserve")}


def scope_hashes(root: Path = ROOT, scope: Sequence[str] = SCOPE) -> Dict[str, str]:
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in scope}


def _lf(b: bytes) -> bytes:
    """CRLF → LF (autocrlf 체크아웃과 blob 비교용)."""
    return b.replace(b"\r\n", b"\n")


def _git(*args, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True)


def check_approval(stage: str, config_hash: str, extractor_version: str, id_hashes: Dict[str, str], frozen_path: Optional[Path] = None,
                   approval_path: Path = APPROVAL, repo: Path = ROOT, cfg: Optional[dict] = None, explore_ids: Optional[Sequence[str]] = None,
                   scope_now: Optional[Dict[str, str]] = None) -> dict:
    if not approval_path.exists():
        raise ApprovalError(f"승인 기록이 없다: {approval_path}")
    a = json.loads(approval_path.read_text(encoding="utf-8"))
    bad = []
    if a.get("status") != "approved":
        bad.append(f"status={a.get('status')!r} (approved 아님)")
    if a.get("stage") != stage:
        bad.append(f"stage={a.get('stage')!r} != {stage!r}")
    for k in ("reviewer", "review_ref"):                    # L2-5: 승인 출처 필수
        if not (isinstance(a.get(k), str) and a[k].strip()):
            bad.append(f"{k} 비어 있음 (승인 출처 필수)")
    if a.get("config_hash") != config_hash:
        bad.append(f"config_hash {str(a.get('config_hash'))[:12]} != 현재 {config_hash[:12]}")
    if a.get("feature_extractor_version") != extractor_version:
        bad.append(f"feature_extractor_version {a.get('feature_extractor_version')!r} != {extractor_version!r}")
    for k, v in id_hashes.items():
        if (a.get("id_set_hashes") or {}).get(k) != v:
            bad.append(f"id_set_hashes[{k}] 불일치")
    scope_now = scope_hashes(repo) if scope_now is None else scope_now      # L2-4: 승인 후 실행 관련 파일 변경 탐지
    rec = a.get("scope_files")
    if not isinstance(rec, dict):
        bad.append("scope_files 없음 (검증 범위 해시 필수)")
    else:
        missing = [p for p in scope_now if p not in rec]
        changed = [p for p in scope_now if p in rec and rec[p] != scope_now[p]]
        if missing:
            bad.append(f"scope_files 에 없는 범위 파일 {missing[:3]}…")
        if changed:
            bad.append(f"승인 이후 실행 관련 파일 변경 {changed[:3]}{'…' if len(changed) > 3 else ''}")
    if stage == "confirm":
        fc = a.get("freeze_commit")
        fz = None
        if frozen_path is None or not frozen_path.exists():
            bad.append("동결 정책 파일 없음")
        else:
            fz_bytes = frozen_path.read_bytes()
            if hashlib.sha256(fz_bytes).hexdigest() != a.get("policy_hash"):
                bad.append("policy_hash != frozen_policy.json 해시")
            try:
                fz = json.loads(fz_bytes.decode("utf-8"))
            except Exception as exc:
                bad.append(f"동결 정책 파일 파싱 실패: {exc}")
        if not fc:
            bad.append("freeze_commit 없음")
        elif _git("cat-file", "-e", f"{fc}^{{commit}}", cwd=repo).returncode != 0:
            bad.append(f"freeze_commit {fc} 가 git 이력에 없다")
        else:
            if _git("merge-base", "--is-ancestor", fc, "HEAD", cwd=repo).returncode != 0:
                bad.append(f"HEAD 가 freeze_commit {fc[:8]} 의 후손이 아니다")
            if frozen_path is not None and frozen_path.exists():                 # L2-3: 동결 산출물이 그 커밋에 들어 있고 blob == 현재 파일
                try:
                    rel = frozen_path.resolve().relative_to(repo.resolve()).as_posix()
                except ValueError:
                    rel = None
                    bad.append(f"동결 정책 파일이 저장소 밖: {frozen_path}")
                if rel:
                    shown = _git("show", f"{fc}:{rel}", cwd=repo)
                    if shown.returncode != 0:
                        bad.append(f"freeze_commit {fc[:8]} 에 {rel} 이 없다 (동결 산출물 미포함 커밋)")
                    elif _lf(shown.stdout) != _lf(frozen_path.read_bytes()):
                        bad.append(f"freeze_commit 의 {rel} blob 이 현재 파일과 다르다")
        if fz is not None:                                                        # L2-1: 동결 파일 내부 대조
            if fz.get("config_sha256") != config_hash:
                bad.append(f"동결 파일 config_sha256 {str(fz.get('config_sha256'))[:12]} != 현재 설정 {config_hash[:12]}")
            if fz.get("features_version") != extractor_version:
                bad.append(f"동결 파일 features_version {fz.get('features_version')!r} != {extractor_version!r}")
            if explore_ids is not None:
                if sorted(fz.get("explore_ids") or []) != sorted(explore_ids):
                    bad.append("동결 파일 explore_ids != 탐색 ID 파일")
                if fz.get("n_explore") != len(explore_ids):
                    bad.append(f"동결 파일 n_explore {fz.get('n_explore')} != {len(explore_ids)}")
            if cfg is not None and fz.get("n_explore") != cfg["sets"]["explore"]["n"]:
                bad.append(f"동결 파일 n_explore {fz.get('n_explore')} != 설정 {cfg['sets']['explore']['n']}")
            g = fz.get("pool_gate") or {}                                         # L2-2: 관문 수치·문턱·판정 일관성
            thr = cfg["pool"]["gate"]["threshold"] if cfg is not None else g.get("threshold")
            try:
                implied = "진행" if float(g["best_rate"]) <= float(thr) else "보류"
            except (KeyError, TypeError, ValueError):
                implied = None
                bad.append("동결 파일 pool_gate 에 best_rate/threshold 가 없다")
            if implied is not None:
                if g.get("threshold") != thr:
                    bad.append(f"동결 파일 관문 문턱 {g.get('threshold')} != 등록 문턱 {thr}")
                if g.get("decision") != implied:
                    bad.append(f"동결 파일 관문 판정 {g.get('decision')!r} 이 수치({g.get('best_rate')} vs {thr})와 안 맞다")
                if a.get("pool_gate") != implied or implied != "진행":
                    bad.append(f"관문: 승인 {a.get('pool_gate')!r} / 동결 {g.get('decision')!r} / 수치 함의 {implied!r} — 전부 '진행' 이어야 한다")
        elif a.get("pool_gate") != "진행":
            bad.append(f"pool_gate={a.get('pool_gate')!r} (진행 아님)")
    if bad:
        raise ApprovalError("승인 대조 실패 — 호출 0회: " + "; ".join(bad))
    return a


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", action="store_true", help="현재 검증 범위 파일 해시를 JSON 으로 출력 (승인 기록 작성용)")
    args = ap.parse_args()
    if args.scope:
        print(json.dumps(scope_hashes(), indent=1))
