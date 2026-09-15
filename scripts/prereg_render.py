"""
scripts/prereg_render.py — PREREG_pilot_v4.md 의 "설정(자동 생성)" 절을 pilot_config_v4.json 에서 만든다 (Week2-J5, 수치 단일 출처).
설정 파일 sha256 을 같이 적어 두어 실행 게이트(pilot_dryrun.gate)가 "PREREG 가 가리키는 설정 == 지금 설정" 을 확인한다.

    python -X utf8 scripts/prereg_render.py            # 갱신
    python -X utf8 scripts/prereg_render.py --check    # 최신인지 확인 (테스트·게이트)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "evidence" / "week2" / "pilot_config_v4.json"
PREREG = ROOT / "evidence" / "week2" / "PREREG_pilot_v4.md"
BEGIN, END = "<!-- config:begin (자동 생성 — scripts/prereg_render.py, 손으로 고치지 않는다) -->", "<!-- config:end -->"


def config_sha256(path: Path = CONFIG) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(cfg: dict, sha: str) -> str:
    s, g, r = cfg["sets"], cfg["pool"]["gate"], cfg["confirm_rule"]
    rows = [("설정 파일 sha256", f"`{sha}`"), ("탐색 N_e", f"{s['explore']['n']} = 프로브 재사용 {s['explore']['probe_reuse_n']} + 신규 s0 {s['explore']['new_s0_n']}"),
            ("뒤집힘 부분집합", f"{s['explore']['flip_subset_n']} × k={s['explore']['flip_k']} ({', '.join(s['explore']['flip_arms'])})"),
            ("확인 N_c", str(s["confirm"]["n"])), ("예비(봉인)", str(s["reserve"]["n"])), ("seed", str(s["seed"])),
            ("arm / k", f"{', '.join(cfg['arms'])} / k={cfg['k']}"), ("모델", f"A={cfg['models']['A']}, B={cfg['models']['B']}, temp {cfg['models']['temperature']}, max_tokens {cfg['models']['max_tokens']}"),
            ("0회차", f"{cfg['round0']['arm']} 1회 × {cfg['round0']['n_tasks']} 과제 → b_cont = 비용 중앙값"),
            ("풀 관문", f"최고 arm 성공률 ≤ {g['threshold']:.0%} → 진행, 초과 → 보류 ({g['basis']})"),
            ("특징 메뉴 / 상한", f"{cfg['features']['menu']} / ≤ {cfg['features']['max_selected']} 열"), ("λ 메뉴 (기본)", f"{cfg['features']['lambda_menu']} ({cfg['features']['lambda_default']})"),
            ("탐색 CV", f"K={cfg['features']['cv']['K']} × R={cfg['features']['cv']['R']}, 부트스트랩 {cfg['features']['n_boot_explore']}, 순열(진단) {cfg['features']['n_perm_diag']}, "
                        f"특징 선택 {cfg['features']['cv_selection']} (겹 안), P2-pre 자기 메뉴 선택 {cfg['features']['pre_own_selection']}; 규칙 {cfg['features']['selection_rule']}"),
            ("비용 관점", f"실험 총지출 = {cfg['cost_views']['experiment_total']}; arm 자체 = {cfg['cost_views']['arm_only_per_task']}; "
                      f"정책 배포 = {cfg['cost_views']['policy_deploy_per_task']}; 고정 배포 = {cfg['cost_views']['fixed_deploy_per_task']}"),
            ("동결 항목", ", ".join(cfg["freeze"]["items"])), ("주 판정", f"{r['primary']}; α={r['alpha']}, 문턱 {r['threshold_pp']}pp; {r['pass']} → 통과, 그 외 {r['else']}"),
            ("CI", r["ci"]), ("의미", r["meaning"]), ("부차", "; ".join(cfg["secondary"])), ("금지", "; ".join(cfg["forbidden"])),
            ("비용", f"탐색 ≈ ${cfg['cost_usd']['explore_estimate']:.0f}, 확인 ≈ ${cfg['cost_usd']['confirm_estimate']:.0f}, 원장 cap ${cfg['cost_usd']['cap']:.0f} ({cfg['cost_usd']['basis']})"),
            ("원장 / run_id", f"{cfg['ledger_id']} / {cfg['run_ids']}"), ("범위", cfg["scope"]),
            ("보고 항목(탐색)", ", ".join(cfg["report_items"]["explore"])), ("보고 항목(확인)", ", ".join(cfg["report_items"]["confirm"]))]
    return "\n".join([BEGIN, "## 설정 (자동 생성 — `pilot_config_v4.json` 이 단일 출처)", "", "| 항목 | 값 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows] + [END])


def current_block(text: str):
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), text, re.S)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    block = render(cfg, config_sha256())
    text = PREREG.read_text(encoding="utf-8")
    m = current_block(text)
    if args.check:
        if m is None or m.group(0) != block:
            print("[prereg_render] PREREG_pilot_v4.md 의 설정 절이 pilot_config_v4.json 과 다르다 — `python scripts/prereg_render.py` 로 갱신")
            return 1
        print("[prereg_render] 최신")
        return 0
    new = text[:m.start()] + block + text[m.end():] if m else text.rstrip("\n") + "\n\n" + block + "\n"
    PREREG.write_text(new, encoding="utf-8")
    print(f"[prereg_render] 갱신: sha256 {config_sha256()[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
