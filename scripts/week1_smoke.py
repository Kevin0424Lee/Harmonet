"""
scripts/week1_smoke.py — 1주차 통과 조건 묶음 스모크 (WEEK1 A6). mock 백엔드, 비용 0.

    python -X utf8 scripts/week1_smoke.py

검사:
  A6-1 single / harmonet(v1) / harmonet_v2 모두 trace 생성 + 스키마 통과
  A6-2 verify 액션은 cost 0, llm_calls 0, token_source "none"
  A6-3 v2 에서 build.model != expert_review.model (BUILDER=mock-a, REVIEWER=mock-b)
  A6-4 HARMONET_LLM_BACKEND 미설정(+키 없음) 시 RuntimeError — 자동 Mock 폴백 없음
  A6-5 v2 어떤 액션에도 trigger="eval:hidden" 없음 (G1_DISABLE_EVAL_REPAIR 기본값)
실패하면 exit 1. trace 는 evidence/week1_smoke/<YYYYMMDD>/ 에 저장.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

OUT = ROOT / "evidence" / "week1_smoke" / time.strftime("%Y%m%d")
os.environ.update({
    "HARMONET_LLM_BACKEND": "mock",
    "HARMONET_ALLOW_NO_REDIS": "1",
    "HARMONET_MODEL_BUILDER": "mock-a",
    "HARMONET_MODEL_REVIEWER": "mock-b",
    "HARMONET_TRACE_DIR": str(OUT.parent),
    "HARMONET_TRACE_RUN_ID": OUT.name,
})
os.environ.pop("G1_DISABLE_EVAL_REPAIR", None)   # 기본값 그대로 (차단)

from benchmark.tasks import BenchmarkTask                       # noqa: E402
from benchmark.agents_single import SingleCallAdapter           # noqa: E402
from benchmark.agents_harmonet import HarmoNetAdapter           # noqa: E402
from benchmark.agents_harmonet_v2 import HarmoNetV2Adapter      # noqa: E402
from harmonet.trace import validate_trace                       # noqa: E402

failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


code_task = BenchmarkTask(id="smoke_code", category="humaneval", prompt="Write a Python function add(a, b) that returns a + b.",
                          expected_keywords=["add"], complexity=1, spec={"kind": "code", "entry_point": "add", "tests": None})
api_task = BenchmarkTask(id="smoke_api", category="api_design", prompt="Design an API with POST endpoints and schemas.",
                         expected_keywords=["POST", "schema"], complexity=2)   # open-ended → v2 reviewer 단계가 돈다

traces: dict[str, dict] = {}
for adapter, task in ((SingleCallAdapter(), code_task), (HarmoNetAdapter(ticks=2), code_task), (HarmoNetV2Adapter(ticks=2), api_task)):
    with contextlib.redirect_stdout(io.StringIO()):
        result = adapter.run(task)
    path = Path(result["trace_path"])
    ok = path.exists()
    data = json.loads(path.read_text(encoding="utf-8")) if ok else {}
    try:
        validate_trace(data)
        schema_ok = True
    except AssertionError as exc:
        schema_ok = False
        print("   schema error:", exc)
    check(ok and schema_ok, f"A6-1 {adapter.name}: trace 생성 + 스키마 ({path})")
    traces[adapter.name] = data

# A6-2
verifies = [a for d in traces.values() for a in d.get("history", []) if a["kind"] == "verify"]
check(bool(verifies) and all(a["cost"]["prompt_tokens"] == 0 and a["cost"]["completion_tokens"] == 0
                             and a["cost"]["llm_calls"] == 0 and a["token_source"] == "none" for a in verifies),
      f"A6-2 verify 액션 {len(verifies)}개: cost 0 / calls 0 / token_source none")

# A6-3
v2 = {a["kind"]: a for a in traces.get("harmonet_v2", {}).get("history", [])}
check("build" in v2 and "expert_review" in v2 and v2["build"]["model"] != v2["expert_review"]["model"],
      f"A6-3 v2 build.model={v2.get('build', {}).get('model')} != expert_review.model={v2.get('expert_review', {}).get('model')}")

# A6-4: 백엔드 미설정 → RuntimeError (별도 프로세스, 키 제거)
env = {k: v for k, v in os.environ.items()
       if k not in ("HARMONET_LLM_BACKEND", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "RUNYOURAI_API_KEY")}
env["OLLAMA_HOST"] = "http://127.0.0.1:1"   # 로컬 Ollama 자동 감지도 막는다
proc = subprocess.run([sys.executable, "-X", "utf8", "-c",
                       "from harmonet.llm import get_llm_client\n"
                       "try:\n    get_llm_client(); print('NO_EXCEPTION')\n"
                       "except RuntimeError as e: print('RUNTIME_ERROR', str(e)[:80])"],
                      capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
check("RUNTIME_ERROR" in proc.stdout, f"A6-4 백엔드 미설정 → RuntimeError ({proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-200:]})")

# A6-5
check(all(a["trigger"] != "eval:hidden" for a in traces.get("harmonet_v2", {}).get("history", []))
      and traces.get("harmonet_v2", {}).get("leak_risk") is False,
      "A6-5 v2 trace 에 trigger=eval:hidden 없음, leak_risk=false")

print(f"\ntraces: {OUT}")
if failures:
    print(f"\n{len(failures)} FAILED:", *failures, sep="\n  ")
    sys.exit(1)
print("\nWeek1 smoke: ALL PASS")
