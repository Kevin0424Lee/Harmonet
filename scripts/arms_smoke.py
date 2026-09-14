"""
scripts/arms_smoke.py — 6 arm 실행기 무유료 종단간 스모크 (Week2-F1 b). 실제 Docker(공식 BCB 이미지), 유효 코드 mock(시나리오), 유료 호출 0.

BCB 적격 과제 3개(개발용 ID: BigCodeBench/3·4·9, 풀에서 제외) × 6 arm × k=2. 시나리오가 arm 마다 정답/오답/근접오답(가시 doctest pass·히든 fail)
을 정하므로 기대 히든 결과가 결정된다. 검사: hidden level=functional, sandbox=docker, exec_count ≥ 1 (모든 arm), 히든 결과 = 기대,
트레이스 스키마(validate_trace)·비용 정합(Σaction == cost_so_far, s0 비용은 shared_s0_cost 에만)·모델 표기(A=sonnet-4-6, B=haiku-4-5 이름만; 호출은 mock).

    python -X utf8 scripts/arms_smoke.py      → evidence/week2/arms_smoke_f1.{json,md}
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from benchmark.mock_scenario import write_bcb_scenario  # noqa: E402
from harmonet.trace import validate_trace               # noqa: E402

DEV_IDS = ["BigCodeBench/3", "BigCodeBench/4", "BigCodeBench/9"]
SCRIPTS = {
    "BigCodeBench/3": {"s0": "near", "A-self": "correct", "A-role": "wrong", "B-expert": "correct", "B-solo": "wrong"},
    "BigCodeBench/4": {"s0": "wrong", "A-self": "near", "A-role": "correct", "B-expert": "wrong", "B-solo": "correct"},
    "BigCodeBench/9": {"s0": "correct", "A-self": "wrong", "A-role": "near", "B-expert": "near", "B-solo": "near"},
}
HIDDEN = {"correct": True, "wrong": False, "near": False}
VISIBLE = {"correct": True, "wrong": False, "near": True}
K = 2


def expected(tid: str, arm: str) -> bool:
    s = SCRIPTS[tid]
    if arm == "T":
        return HIDDEN[s["s0"]]
    if arm == "A-selfxk":                       # stop_on_visible_pass: s0 가 가시 pass 면 호출 0회, 아니면 A-self 변형으로 수렴
        return HIDDEN[s["s0"]] if VISIBLE[s["s0"]] else HIDDEN[s["A-self"]]
    return HIDDEN[s[arm]]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="arms_smoke_f1_"))
    sc_path = tmp / "scenario.json"
    write_bcb_scenario(DEV_IDS, SCRIPTS, sc_path, tokens={"prompt": 1000, "completion": 700})
    ids = tmp / "ids.json"; ids.write_text(json.dumps({"ids": DEV_IDS}), encoding="utf-8")
    env = dict(os.environ, HARMONET_LLM_BACKEND="mock-scenario", HARMONET_MOCK_SCENARIO=str(sc_path), HARMONET_MODEL_BUILDER="claude-sonnet-4-6",
               HARMONET_MODEL_REVIEWER="claude-haiku-4-5", HARMONET_ALLOW_NO_REDIS="1", HARMONET_TRACE_RUN_ID="arms_smoke_f1", HARMONET_BUDGET_CAP="5",
               HARMONET_BUDGET_ROOT=str(tmp / "budget"), HARMONET_ARMS_ROOT=str(tmp / "arms"), HARMONET_TRACE_DIR=str(tmp / "traces"), PYTHONIOENCODING="utf-8")
    out = tmp / "arms.json"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", "benchmark.arms", "--pool", "bcb", "--ids", str(ids), "--output", str(out),
                        "--b-cont", "0.05", "--a-call-median", "0.02", "--k", str(K)], cwd=str(ROOT), env=env, text=True)
    assert p.returncode == 0, p.returncode
    d = json.loads(out.read_text(encoding="utf-8"))
    rows = d["rows"]
    assert len(rows) == 3 * 6 * K, len(rows)
    table, n_eh, mismatches = [], 0, []
    for r in rows:
        tr = json.loads(Path(r["trace_path"]).read_text(encoding="utf-8"))
        validate_trace(tr)
        assert tr["cost_attribution"] == "per_call" and tr["cost_so_far"]["cost_usd_unknown_actions"] == 0
        assert tr["score"]["trigger"] == "post_hoc" and tr["history"][-1]["kind"] == "terminate"
        n_eh += sum(a["trigger"] == "eval:hidden" for a in tr["history"])
        assert abs(tr["cost_so_far"]["cost_usd"] - r["cost_usd"]) < 1e-9
        assert all(a["cost"]["llm_calls"] == 0 for a in tr["history"] if "replayed_from_s0" in a["flags"]), "s0 재생 행동에 비용이 붙었다"
        exp = expected(r["task_id"], r["arm"])
        ok = (r["hidden_pass"] is exp) and r["hidden_level"] == "functional" and r["hidden_sandbox"].startswith("docker") and r["hidden_exec_count"] >= 1
        if not ok:
            mismatches.append((r["task_id"], r["arm"], r["rep"], r["hidden_pass"], exp, r["hidden_level"], r["hidden_exec_count"], r["outcome"]))
        table.append((r["task_id"], r["arm"], r["rep"], r["hidden_level"], r["hidden_sandbox"].split(":")[0], r["hidden_exec_count"], r["hidden_pass"], exp,
                      r["n_calls"], ",".join(r["models"]), r["cost_usd"]))
    assert n_eh == 0
    assert not mismatches, mismatches
    md = ["# arms 스모크 F1-b (실제 Docker, 시나리오 mock, 유료 0) — %s" % d["run_id"], "",
          f"3 과제 × 6 arm × k={K} = {len(rows)} 행. 기대 일치 {len(rows) - len(mismatches)}/{len(rows)}, eval:hidden 0, 모든 행 hidden level=functional·sandbox=docker·exec_count≥1.",
          f"비용: arm 단독 합 ${d['cost']['arms_own_usd']} + shared_s0 ${d['cost']['shared_s0_cost_total']} = 총지출 ${d['cost']['total_spent_usd']} (가격표 이름만 빌린 mock 토큰, 실제 지출 0).", "",
          "| task | arm | rep | level | sandbox | exec_count | hidden | 기대 | n_calls | models | cost_usd |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    md += ["| " + " | ".join(str(x) for x in row) + " |" for row in table]
    (ROOT / "evidence/week2/arms_smoke_f1.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "evidence/week2/arms_smoke_f1.json").write_text(json.dumps({"run_id": d["run_id"], "scripts": SCRIPTS, "summary": d["summary"], "cost": d["cost"],
                                                                        "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"arms smoke OK: rows={len(rows)} mismatches=0 eval:hidden=0 cost={d['cost']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
