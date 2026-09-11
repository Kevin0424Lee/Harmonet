"""
compare_runs.py — 구 측정 vs 신 측정 비교표 생성

사용법:
    python compare_runs.py OLD.csv NEW.csv
예:
    python compare_runs.py evidence/g1/g1_v2_final_4way_20x3.csv g1_fair_20x3.csv
"""
import csv
import sys
from collections import defaultdict


def load(path):
    agg = defaultdict(lambda: {"p": 0, "c": 0, "n": 0, "pass": 0, "src": set()})
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            a = agg[r["system"]]
            a["p"] += int(r.get("prompt_tokens") or 0)
            a["c"] += int(r.get("completion_tokens") or 0)
            a["n"] += 1
            a["pass"] += 1 if str(r.get("passed", "")).lower() in ("true", "1") else 0
            a["src"].add(r.get("token_source", "unknown"))
    return agg


def short(name):
    for k in ("harmonet_v2", "harmonet", "langraph", "langgraph", "autogen", "crewai"):
        if k in name:
            return k
    return name[:20]


def main(old_path, new_path):
    old, new = load(old_path), load(new_path)
    old_s = {short(k): v for k, v in old.items()}
    new_s = {short(k): v for k, v in new.items()}

    print(f"구 측정: {old_path}")
    print(f"신 측정: {new_path}")
    print()
    print(f"{'system':14s}{'구_토큰':>9s}{'신_토큰':>9s}{'변화':>9s}{'구_정확':>9s}{'신_정확':>9s}  출처")
    print("-" * 76)
    for k in sorted(set(old_s) | set(new_s)):
        o, n = old_s.get(k), new_s.get(k)
        ot = (o["p"] + o["c"]) / o["n"] if o and o["n"] else 0
        nt = (n["p"] + n["c"]) / n["n"] if n and n["n"] else 0
        oa = 100 * o["pass"] / o["n"] if o and o["n"] else 0
        na = 100 * n["pass"] / n["n"] if n and n["n"] else 0
        delta = f"{(nt/ot - 1)*100:+.0f}%" if ot and nt else "-"
        src = ",".join(sorted(n["src"])) if n else "-"
        print(f"{k:14s}{ot:9.1f}{nt:9.1f}{delta:>9s}{oa:8.1f}%{na:8.1f}%  {src}")

    print()
    base = None
    for k in ("langgraph", "langraph"):
        if k in new_s and new_s[k]["n"]:
            base = (new_s[k]["p"] + new_s[k]["c"]) / new_s[k]["n"]
            break
    if base:
        print("신 측정 기준 LangGraph 대비 절감률")
        for k, v in sorted(new_s.items()):
            if v["n"] and k not in ("langgraph", "langraph"):
                t = (v["p"] + v["c"]) / v["n"]
                print(f"  {k:14s} {100*(1-t/base):6.1f}%")

    print()
    mixed = {k for k, v in new_s.items() if len(v["src"]) > 1 or "estimated" in v["src"]}
    if mixed:
        print("⚠️  추정치가 섞인 시스템:", ", ".join(sorted(mixed)))
        print("   이 시스템과의 비교는 논문에서 반드시 출처를 명시해야 합니다.")
    else:
        print("✅ 전 시스템 실측 — 비교 가능")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
