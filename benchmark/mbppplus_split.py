"""
benchmark/mbppplus_split.py — MBPP+ 제외 집합 + 프로브/확인 집합 동결 (Week2-B0).

    python -X utf8 -m benchmark.mbppplus_split

제외(EXCLUDED): (1) G1 external 에서 이미 돌린 sanitized-MBPP 첫 20개 id, (2) 개발 중 손댄 과제 — 스모크로 돌린 5개,
  특수 판정(집합 비교·not-None·특수 오라클) 과제 전부(동등성 테스트에서 entry_point 별로 손댐), (3) 스펙 생성에서 제외된 2개(크기),
  (4) plus 입력이 0개라 plus_only_pass 를 정의할 수 없는 과제(Mbpp/793).
프로브 = 남은 과제에서 seed 고정 60개. 확인 집합 = 그 나머지 전부(≥200 이어야 하며, 아니면 파일을 쓰지 않고 실패).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from benchmark.mbppplus import load_spec

SEED = 20260913
N_PROBE = 60
G1_FIRST20 = [2, 3, 4, 6, 7, 8, 9, 11, 12, 14, 16, 17, 18, 19, 20, 56, 57, 58, 59, 61]      # evidence/g1_fair/*.csv
DEV_SMOKE = [2, 3, 4, 6, 7]                                                                # 로더 스모크
SPECIAL_VERDICT = [2, 7, 111, 140, 232, 558, 579, 581, 737, 769, 787, 794, 164, 295]      # 집합비교·not-None·특수 오라클
OUT_DIR = Path(__file__).resolve().parent.parent / "evidence" / "week2"


def main() -> int:
    spec = load_spec()
    all_ids = sorted(spec["tasks"], key=lambda s: int(s.split("/")[1]))
    excluded = {f"Mbpp/{n}" for n in G1_FIRST20 + DEV_SMOKE + SPECIAL_VERDICT}
    no_plus = [t for t in all_ids if not spec["tasks"][t]["hidden_tests"]]     # plus 입력이 0개(Mbpp/793) → plus_only_pass 정의 불가
    pool = [t for t in all_ids if t not in excluded and t not in no_plus]
    rng = random.Random(SEED)
    probe = sorted(rng.sample(pool, N_PROBE), key=lambda s: int(s.split("/")[1]))
    confirm = [t for t in pool if t not in set(probe)]
    print(f"spec tasks={len(all_ids)} excluded(in spec)={len(excluded & set(all_ids))} pool={len(pool)} probe={len(probe)} confirm={len(confirm)}")
    if len(confirm) < 200:
        raise SystemExit(f"확인 집합 {len(confirm)} < 200 — 동결하지 않는다")
    meta = {"dataset": "MBPP+", "version": spec["source"]["version"], "spec_sha256": __import__("benchmark.mbppplus", fromlist=["SPEC_SHA256"]).SPEC_SHA256,
            "seed": SEED, "excluded": {"g1_first20": G1_FIRST20, "dev_smoke": DEV_SMOKE, "special_verdict": SPECIAL_VERDICT,
                                       "no_plus_inputs": no_plus, "spec_excluded": spec["excluded"]}}
    (OUT_DIR / "probe_ids_mbppplus.json").write_text(json.dumps({**meta, "n": len(probe), "ids": probe}, indent=1), encoding="utf-8")
    (OUT_DIR / "confirm_ids_mbppplus.json").write_text(json.dumps({**meta, "n": len(confirm), "ids": confirm}, indent=1), encoding="utf-8")
    print("wrote", OUT_DIR / "probe_ids_mbppplus.json", OUT_DIR / "confirm_ids_mbppplus.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
