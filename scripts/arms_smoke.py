"""
scripts/arms_smoke.py — 6 arm 실행기 스모크 (Week2-D5). mock 백엔드, BCB 적격 과제 3개(개발용 ID 로 기록·풀 제외), 유료 호출 0.

확인: (1) 과제마다 6 arm trace 가 있고 validate_trace 통과, (2) 비용 정합 (per_call: Σaction == cost_so_far, 미측정 0), (3) 모델 분리
(A 계열 arm 은 mock-a 만, B-expert 는 build 재생=mock-a + review=mock-b, B-solo 는 mock-b 만 호출), (4) trigger=eval:hidden 0건,
score.trigger=post_hoc, (5) s0 파일 4개 + arm_order.json 존재, 계속 arm 의 build 행동 input_ref 가 s0 파일.

    python -X utf8 scripts/arms_smoke.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harmonet.trace import validate_trace  # noqa: E402

DEV_IDS = ["BigCodeBench/3", "BigCodeBench/4", "BigCodeBench/9"]   # 적격 과제 중 개발용으로 소모 — bcb_eligibility.DEV_IDS 에 등록해 풀에서 제외
tmp = Path(tempfile.mkdtemp(prefix="arms_smoke_"))
ids = tmp / "ids.json"; ids.write_text(json.dumps({"ids": DEV_IDS}), encoding="utf-8")
env = dict(os.environ, HARMONET_LLM_BACKEND="mock", HARMONET_MODEL_BUILDER="mock-a", HARMONET_MODEL_REVIEWER="mock-b", HARMONET_ALLOW_NO_REDIS="1",
           HARMONET_TRACE_RUN_ID="arms_smoke", HARMONET_BUDGET_CAP="1", HARMONET_BUDGET_ROOT=str(tmp / "budget"), HARMONET_ARMS_ROOT=str(tmp / "arms"),
           HARMONET_TRACE_DIR=str(tmp / "traces"), PYTHONIOENCODING="utf-8")
out = tmp / "arms.json"
rc = subprocess.run([sys.executable, "-X", "utf8", "-m", "benchmark.arms", "--pool", "bcb", "--ids", str(ids), "--output", str(out),
                     "--b-cont", "0.02", "--a-call-median", "0.003"], cwd=str(ROOT), env=env).returncode
assert rc == 0, rc
d = json.loads(out.read_text(encoding="utf-8"))
flat = [r for t in d["tasks"] for r in t["rows"]]
assert len(flat) == 18 and {r["arm"] for r in flat} == {"T", "A-self", "A-selfxk", "A-role", "B-expert", "B-solo"}
n_eh = 0
for r in flat:
    tr = json.loads(Path(r["trace_path"]).read_text(encoding="utf-8"))
    validate_trace(tr)
    assert tr["cost_attribution"] == "per_call" and tr["cost_so_far"]["cost_usd_unknown_actions"] == 0 and tr["cost_so_far"]["cost_usd"] is not None
    assert tr["score"]["trigger"] == "post_hoc" and tr["history"][-1]["kind"] == "terminate"
    n_eh += sum(a["trigger"] == "eval:hidden" for a in tr["history"])
    models = {a["model"] for a in tr["history"] if a["model"] != "none"}
    llm_kinds = [(a["kind"], a["model"]) for a in tr["history"] if a["model"] != "none"]
    if r["arm"] in ("T", "A-self", "A-selfxk", "A-role"):
        assert models == {"mock-a"}, (r["arm"], models)
    elif r["arm"] == "B-expert":
        assert models == {"mock-a", "mock-b"} and llm_kinds[0] == ("build", "mock-a") and all(m == "mock-b" for k, m in llm_kinds[1:]), llm_kinds
    elif r["arm"] == "B-solo":
        new_calls = [a for a in tr["history"] if a["model"] != "none" and "replayed_from_s0" not in a["flags"]]
        assert all(a["model"] == "mock-b" for a in new_calls) and new_calls, llm_kinds
    if r["arm"] != "T":
        assert any(x.endswith("prompt_context.json") for a in tr["history"] for x in a["input_ref"]), "계속 arm 의 build 재생에 s0 input_ref 없음"
    s0 = Path(r["s0_dir"])
    assert all((s0 / n).exists() for n in ("artifact.py", "verify_visible.json", "prompt_context.json", "decision_signals.json"))
    assert (s0.parent / "arm_order.json").exists()
assert n_eh == 0
print(f"arms smoke OK: tasks={len(d['tasks'])} rows={len(flat)} eval:hidden={n_eh} orders={[t['order'] for t in d['tasks']]}")
print("summary:", json.dumps(d["summary"], ensure_ascii=False)[:400])
