"""
benchmark/bcb_split.py — BCB 적격 풀 → 프로브 60 (seed 고정) / 확인 집합 (Week2-C0 2-5, 사전 등록).

    python -X utf8 -m benchmark.bcb_split                 # 프로브 ID 파일만 (사전 등록 시)
    python -X utf8 -m benchmark.bcb_split --freeze-confirm  # 프로브 판정 통과 뒤 확인 집합 동결

풀 = evidence/week2/bcb_eligibility.json 의 eligible_ids (관문 1 ∧ 2, 개발용 ID 제외). 확인 집합 = 풀 − 프로브 (≥200 아니면 멈춤).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SEED = 20260913
N_PROBE = 60
DIR = Path(__file__).resolve().parent.parent / "evidence" / "week2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-confirm", action="store_true")
    args = ap.parse_args()
    elig = json.loads((DIR / "bcb_eligibility.json").read_text(encoding="utf-8"))
    pool = sorted(elig["eligible_ids"], key=lambda s: int(s.split("/")[1]))
    if len(pool) < N_PROBE + 200:
        raise SystemExit(f"적격 풀 {len(pool)} < 프로브 60 + 확인 200 — 멈춤")
    probe = sorted(random.Random(SEED).sample(pool, N_PROBE), key=lambda s: int(s.split("/")[1]))
    confirm = [t for t in pool if t not in set(probe)]
    meta = {"dataset": "BigCodeBench Complete", "revision": elig["source"]["revision"], "file_sha256": elig["source"]["sha256"],
            "image": elig["source"]["image"], "seed": SEED, "n_pool": len(pool), "dev_ids": elig["dev_ids"]}
    (DIR / "probe_ids_bcb.json").write_text(json.dumps({**meta, "n": len(probe), "ids": probe}, indent=1), encoding="utf-8")
    print(f"pool={len(pool)} probe={len(probe)} confirm(if frozen)={len(confirm)} → {DIR / 'probe_ids_bcb.json'}")
    if args.freeze_confirm:
        (DIR / "confirm_ids_bcb.json").write_text(json.dumps({**meta, "n": len(confirm), "ids": confirm}, indent=1), encoding="utf-8")
        print("frozen:", DIR / "confirm_ids_bcb.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
