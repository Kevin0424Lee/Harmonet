"""
benchmark/lcb.py — LiveCodeBench code_generation_lite 로더 (Week2-A0)

데이터: HF `livecodebench/code_generation_lite`, **revision 고정** (LCB_REVISION). 로딩 스크립트(trust_remote_code)는 쓰지 않고
jsonl 파일을 revision URL 로 직접 받는다. release 별 파일: release_v6 = test.jsonl … test6.jsonl.

private_test_cases 인코딩: base64 → zlib → **pickle** (JSON 문자열). pickle 은 임의 코드를 실행할 수 있으므로
**공식 출처(HF livecodebench/code_generation_lite) + 위 고정 revision 에서 받은 파일만** 역직렬화한다. 다른 출처의 파일은 넣지 않는다.

필터: testtype == "stdin" 만 (functional 제외 — 우리 하네스는 stdio 판정). 난이도·날짜는 호출자가 지정 (사전 등록값).
"""
from __future__ import annotations

import base64
import json
import pickle
import urllib.request
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

LCB_REPO = "livecodebench/code_generation_lite"
LCB_REVISION = "0fe84c3912ea0c4d4a78037083943e8f0c4dd505"   # HF main @ 2025-06-05 (확인 2026-09-13)
LCB_RELEASE = "release_v6"
LCB_FILES = {"release_v6": ["test.jsonl", "test2.jsonl", "test3.jsonl", "test4.jsonl", "test5.jsonl", "test6.jsonl"]}
DATA_DIR = Path(__file__).resolve().parent.parent / "benchmark_data" / "lcb"


@dataclass
class LcbTask:
    question_id: str
    title: str
    difficulty: str
    contest_date: str          # ISO
    platform: str
    prompt: str                # 문제 설명 + public 예제 (private 없음)
    public_tests: List[Dict[str, str]]
    private_tests: List[Dict[str, str]]
    starter_code: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def spec(self) -> Dict[str, Any]:
        return {"kind": "stdio", "tests": self.public_tests, "hidden_tests": self.private_tests, "hidden_exposed": False}


def _download(name: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / name
    if not path.exists():
        url = f"https://huggingface.co/datasets/{LCB_REPO}/resolve/{LCB_REVISION}/{name}"
        print(f"[lcb] downloading {url}")
        urllib.request.urlretrieve(url, path)
    return path


def _decode_private(blob: str) -> List[Dict[str, str]]:
    # 공식 출처 + 고정 revision 파일만 역직렬화 (모듈 docstring). 형식: base64 → zlib → pickle → JSON 문자열
    raw = pickle.loads(zlib.decompress(base64.b64decode(blob)))
    return json.loads(raw) if isinstance(raw, (str, bytes)) else raw


def _build_prompt(r: Dict[str, Any], public: List[Dict[str, str]]) -> str:
    examples = "\n\n".join(f"Sample Input {i + 1}:\n{t['input'].rstrip()}\nSample Output {i + 1}:\n{t['output'].rstrip()}"
                           for i, t in enumerate(public))
    return (
        "Solve this competitive programming problem in Python 3. Read all input from standard input and write the answer to "
        "standard output. Return exactly one fenced ```python code block containing the complete program and nothing else.\n\n"
        f"### Problem: {r['question_title']}\n\n{r['question_content'].strip()}\n\n### Public examples\n{examples}\n"
    )


def load_lcb(files: Optional[List[str]] = None, *, stdin_only: bool = True, difficulty: Optional[List[str]] = None,
             min_date: Optional[str] = None, max_date: Optional[str] = None) -> List[LcbTask]:
    tasks: List[LcbTask] = []
    for name in files or LCB_FILES[LCB_RELEASE]:
        for line in _download(name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            public = json.loads(r["public_test_cases"])
            types = {t.get("testtype") for t in public}
            if stdin_only and types != {"stdin"}:
                continue
            if difficulty and r["difficulty"] not in difficulty:
                continue
            date = r["contest_date"][:10]
            if (min_date and date < min_date) or (max_date and date > max_date):
                continue
            private = _decode_private(r["private_test_cases"])
            tasks.append(LcbTask(
                question_id=r["question_id"], title=r["question_title"], difficulty=r["difficulty"], contest_date=date,
                platform=r["platform"], prompt=_build_prompt(r, public),
                public_tests=[{"input": t["input"], "output": t["output"]} for t in public],
                private_tests=[{"input": t["input"], "output": t["output"]} for t in private],
                starter_code=r.get("starter_code") or "", meta={"source_file": name, "revision": LCB_REVISION},
            ))
    return tasks


def count_table(tasks: List[LcbTask]) -> str:
    """난이도 × 월 표 (프로브 전 보고용)."""
    import collections
    tab = collections.Counter((t.difficulty, t.contest_date[:7]) for t in tasks)
    months = sorted({m for _, m in tab})
    lines = ["| difficulty | " + " | ".join(months) + " | total |", "|---|" + "---|" * (len(months) + 1)]
    for d in ("easy", "medium", "hard"):
        lines.append(f"| {d} | " + " | ".join(str(tab[(d, m)]) for m in months) + f" | {sum(tab[(d, m)] for m in months)} |")
    return "\n".join(lines)


if __name__ == "__main__":
    ts = load_lcb(["test5.jsonl", "test6.jsonl"])
    print(f"stdin tasks in test5+test6: {len(ts)}")
    print(count_table(ts))
    t = ts[0]
    print(t.question_id, t.difficulty, t.contest_date, "public", len(t.public_tests), "private", len(t.private_tests))
    assert "private" not in t.prompt.lower() and all(p["output"] in t.prompt for p in t.public_tests)
    print("lcb.py self-check OK")
