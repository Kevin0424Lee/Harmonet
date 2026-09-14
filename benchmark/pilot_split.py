"""
benchmark/pilot_split.py — 파일럿 ID 동결 (Week2-I2). 실행 아님.

탐색 집합 = 프로브 60 중 재적격(F5) 통과 59 (565 는 필터 v2 로 제외). 뒤집힘 부분집합 = 탐색 집합에서 seed 고정 30.
확인 집합 = 미사용 344(적격 403 − 프로브 60 전부) 에서 seed 고정 N=200. 나머지 144 = 예비.
    python -X utf8 -m benchmark.pilot_split
"""
from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20260915
DIR = Path(__file__).resolve().parent.parent / "evidence" / "week2"


def main() -> int:
    elig = json.loads((DIR / "bcb_eligibility.json").read_text(encoding="utf-8"))
    pool = set(elig["eligible_ids"])
    probe = json.loads((DIR / "probe_ids_bcb.json").read_text(encoding="utf-8"))["ids"]
    explore = [t for t in probe if t in pool]
    dropped = [t for t in probe if t not in pool]
    unused = sorted(pool - set(probe), key=lambda s: int(s.split("/")[1]))
    rng = random.Random(SEED)
    flip = sorted(rng.sample(explore, 30), key=lambda s: int(s.split("/")[1]))
    confirm = sorted(rng.sample(unused, 200), key=lambda s: int(s.split("/")[1]))
    reserve = [t for t in unused if t not in set(confirm)]
    meta = {"dataset": "BigCodeBench Complete", "eligibility": elig["source"], "n_eligible": len(pool), "seed": SEED}
    (DIR / "pilot_explore_ids_bcb.json").write_text(json.dumps({**meta, "n": len(explore), "ids": explore, "dropped_from_probe": dropped,
                                                              "flip_subset_n": 30, "flip_subset_ids": flip}, indent=1), encoding="utf-8")
    (DIR / "pilot_confirm_ids_bcb.json").write_text(json.dumps({**meta, "n": len(confirm), "ids": confirm}, indent=1), encoding="utf-8")
    (DIR / "pilot_reserve_ids_bcb.json").write_text(json.dumps({**meta, "n": len(reserve), "ids": reserve}, indent=1), encoding="utf-8")
    print(f"eligible={len(pool)} explore={len(explore)} (dropped {dropped}) flip=30 unused={len(unused)} confirm={len(confirm)} reserve={len(reserve)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
