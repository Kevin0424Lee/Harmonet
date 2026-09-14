"""
benchmark/pilot_split.py — 파일럿 ID 동결 (Week2-I2). 실행 아님.

탐색 집합(v4, J3) = 프로브 60 중 재적격(F5) 통과 59 (565 는 필터 v2 로 제외; s0 는 프로브 산출물 재사용, 성공 여부로 선별하지 않는다)
                 + 예비 144 에서 seed 고정 41 (s0 새로 생성) → N_e = 100. 뒤집힘 부분집합 = 프로브 59 에서 seed 고정 30 (v3 과 동일).
확인 집합 = 미사용 344(적격 403 − 프로브 60 전부) 에서 seed 고정 N=200 (v3 과 바이트 동일 — 추출 순서가 앞이라 41 추가로 바뀌지 않는다). 예비 = 103 봉인.
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
    reserve_v3 = [t for t in unused if t not in set(confirm)]                      # 144
    extra = sorted(rng.sample(reserve_v3, 41), key=lambda s: int(s.split("/")[1]))   # v4: 탐색 보충 41 (확인 200 추출 뒤라 확인은 불변)
    reserve = [t for t in reserve_v3 if t not in set(extra)]                        # 103 봉인
    explore_all = sorted(explore + extra, key=lambda s: int(s.split("/")[1]))
    meta = {"dataset": "BigCodeBench Complete", "eligibility": elig["source"], "n_eligible": len(pool), "seed": SEED}
    (DIR / "pilot_explore_ids_bcb.json").write_text(json.dumps({**meta, "version": "v4", "n": len(explore_all), "ids": explore_all,
                                                              "probe_reuse_n": len(explore), "probe_reuse_ids": explore, "new_s0_n": len(extra), "new_s0_ids": extra,
                                                              "sources": {**{t: "probe_reuse" for t in explore}, **{t: "new" for t in extra}},   # K3: 실행기 분기 키
                                                              "dropped_from_probe": dropped, "flip_subset_n": 30, "flip_subset_ids": flip}, indent=1), encoding="utf-8")
    (DIR / "pilot_confirm_ids_bcb.json").write_text(json.dumps({**meta, "n": len(confirm), "ids": confirm}, indent=1), encoding="utf-8")
    (DIR / "pilot_reserve_ids_bcb.json").write_text(json.dumps({**meta, "version": "v4", "n": len(reserve), "ids": reserve}, indent=1), encoding="utf-8")
    print(f"eligible={len(pool)} explore={len(explore_all)} (probe {len(explore)}, dropped {dropped}, new {len(extra)}) flip=30 unused={len(unused)} "
          f"confirm={len(confirm)} reserve={len(reserve)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
