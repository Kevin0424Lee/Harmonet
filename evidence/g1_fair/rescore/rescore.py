"""
A7c 재채점 대조. 새 채점기(score_hidden, result.json+nonce)로 돌린 7B norepair 20x3 결과의 candidate_code 를
구 채점기(종료 코드 0 = 통과)에 다시 넣어 같은 후보에 대한 두 판정을 비교한다 (같은 후보이므로 표본 차이 없음).
추가로 구 CSV(evidence/g1_fair/rerun/*.csv, 후보 미저장)와 과제별 통과 수를 대조한다 (별도 실행이라 원인 귀속 불가).

    python -X utf8 evidence/g1_fair/rescore/rescore.py
"""
import collections
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmark.external_g1 import evaluate_code_exitcode_legacy, load_humaneval, load_mbpp  # noqa: E402

HERE = Path(__file__).parent
NEW = HERE / "g1_rescore_7b_norepair_20x3.csv"
OLD = {"single": ROOT / "evidence/g1_fair/rerun/g1_fair_single_norepair_fixedep_20x3.csv",
       "harmonet_v2": ROOT / "evidence/g1_fair/rerun/g1_fair_v2_norepair_fixedep_20x3.csv",
       "harmonet": ROOT / "evidence/g1_fair/rerun/g1_fair_v1_norepair_20x3.csv"}

tasks = {t.task_id: t for t in load_humaneval(20) + load_mbpp(20)}
csv.field_size_limit(10_000_000)
rows = list(csv.DictReader(open(NEW, encoding="utf-8")))

# ── 1. 같은 후보, 두 채점기 ──
flips = []           # 구=통과, 신=불통과 (거짓 통과)
reverse = []         # 구=불통과, 신=통과
by_sys = collections.defaultdict(lambda: collections.Counter())
for r in rows:
    t = tasks[r["task_id"]]
    legacy, _ = evaluate_code_exitcode_legacy(r["candidate_code"], t, 60.0)
    new = r["passed"] == "True"
    by_sys[r["system"]]["n"] += 1
    by_sys[r["system"]]["legacy_pass"] += legacy
    by_sys[r["system"]]["new_pass"] += new
    if legacy and not new:
        flips.append((r["system"], r["task_id"], r["repeat"], r["outcome"], r["eval_error"][:120]))
    elif new and not legacy:
        reverse.append((r["system"], r["task_id"], r["repeat"]))

# ── 2. 구 CSV 와 과제별 통과 수 대조 (별도 실행이므로 표본 노이즈 포함) ──
def per_task(rows_):
    c = collections.Counter()
    for r in rows_:
        if r["passed"] == "True":
            c[r["task_id"]] += 1
    return c

out = ["# 재채점 대조 (A7c) — 7B norepair 20×3, 2026-09-13", "",
       "## 1. 같은 후보를 두 채점기로 (같은 후보이므로 표본 차이 없음)", "",
       "**적용 범위:** 이 결과는 **이번에 저장한 후보 360개에 한한다.** 후보를 저장하지 않은 과거 실행(6월, 9월 11·12일 CSV)에는 소급 적용할 수 없다 — 그 실행들에서 종료 코드 위조가 없었다는 것은 확인되지 않았고, 확인할 방법도 없다.", "",
       "| system | n | 구 채점기(종료 코드) 통과 (HumanEval 히든 + MBPP 공개 혼합, 대조 목적) | 새 채점기 통과 (동일 혼합) | 거짓 통과(구=통과·신=불통과) | 역전(구=불통과·신=통과) |", "|---|---|---|---|---|---|"]
for s, c in by_sys.items():
    fp = sum(1 for f in flips if f[0] == s)
    rv = sum(1 for f in reverse if f[0] == s)
    out.append(f"| {s} | {c['n']} | {c['legacy_pass']} ({100*c['legacy_pass']/c['n']:.1f}%) | {c['new_pass']} ({100*c['new_pass']/c['n']:.1f}%) | **{fp}** ({100*fp/c['n']:.1f}%) | {rv} |")
out += ["", "### 뒤집힌 행 (거짓 통과)", ""]
out += ["| system | task | repeat | 새 outcome | eval_error |", "|---|---|---|---|---|"] + \
       [f"| {s} | {t} | {rp} | {o} | {e.replace('|', '/')} |" for s, t, rp, o, e in flips] if flips else ["(없음)"]
if reverse:
    out += ["", "### 역전 행 (구=불통과, 신=통과)", "", "| system | task | repeat |", "|---|---|---|"] + [f"| {s} | {t} | {rp} |" for s, t, rp in reverse]
out += ["", "## 2. 구 CSV(후보 미저장, 별도 실행) 와 과제별 통과 수 대조 — 별도 실행이라 차이의 원인 귀속 불가, 참고용", ""]
for s, path in OLD.items():
    if not path.exists():
        out.append(f"- {s}: 구 CSV 없음"); continue
    old = per_task(list(csv.DictReader(open(path, encoding="utf-8"))))
    new = per_task([r for r in rows if r["system"] == s])
    diff = {t: (old[t], new[t]) for t in sorted(set(old) | set(new)) if old[t] != new[t]}
    out.append(f"- **{s}**: 구 통과 {sum(old.values())}/120 → 신 통과 {sum(new.values())}/120; 과제별 통과 수가 다른 과제 {len(diff)}/40: "
               + ", ".join(f"{t}({o}→{n})" for t, (o, n) in diff.items()))
out += ["", "## 3. 추출 방식 분포 (extraction) 와 outcome 분포", ""]
for s in by_sys:
    ex = collections.Counter(r["extraction"] for r in rows if r["system"] == s)
    oc = collections.Counter(r["outcome"] for r in rows if r["system"] == s)
    out.append(f"- {s}: extraction {dict(ex)} | outcome {dict(oc)}")
out += ["", "MBPP 행은 `hidden_exposed=True` (채점 test_list 가 프롬프트에 공개) — 히든 점수가 아니다. HumanEval 행만 히든 채점."]
(HERE.parent / "RESCORE.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
