"""
benchmark/bcb.py — BigCodeBench 로더 (Week2-C0). Complete 설정.

데이터: HF `bigcode/bigcodebench`, 파일 data/v0.1.4-00000-of-00001.parquet, **revision + sha256 고정**. 다른 파일이면 RuntimeError.
필드: task_id, complete_prompt(모델 프롬프트, 그대로), doc_struct(예제 추출용), entry_point, libs, canonical_solution(적격성 판정 전용), test(히든 채점 전용).
canonical_solution 과 test 는 생성·수리·리뷰 경로 어디에도 나가지 않는다 — BcbTask.prompt 는 complete_prompt 뿐이고, 두 필드는 spec() 의
hidden 쪽(`hidden_tests`)과 적격성 스크립트(bcb_eligibility.py)만 읽는다.

가시 테스트 후보 = doc_struct["examples"] 의 doctest 블록 (기대 출력이 있는 예제 ≥1). 채택 여부는 bcb_eligibility.py 가 정한다
(정적 스크린 + 공식 이미지에서 canonical 2회 실행 일치).
"""
from __future__ import annotations

import ast
import doctest
import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

BCB_REPO = "bigcode/bigcodebench"
BCB_REVISION = "b74c0d0bf70d2c0bc459be537895cca163007f1a"     # HF main @ 2025-04-30 (확인 2026-09-14)
BCB_FILE = "data/v0.1.4-00000-of-00001.parquet"
BCB_SHA256 = "d9a4965821c9507ebdfb551c288656b2d5fe553234f5183044333ca8a4018267"
DATA_DIR = Path(__file__).resolve().parent.parent / "benchmark_data" / "bcb"

# 정적 스크린: 예제 소스·기대 출력에 이런 게 보이면 난수·시간·네트워크·파일시스템·플롯 의존으로 보고 가시 테스트에서 뺀다 (Week2-C0 2-3)
_NONDET_RE = re.compile(r"\b(random|randint|shuffle|seed|time\.|datetime|\.now\(|today\(|uuid|requests|urllib|socket|http|"
                        r"open\(|os\.(remove|listdir|path|makedirs|getcwd|environ)|shutil|tempfile|Path\(|glob|plt|pyplot|Axes|Figure|"
                        r"savefig|\.show\(|input\(|subprocess|getpass)\b|<[\w.]+ object at 0x|<[\w.]+ at 0x")


@dataclass
class BcbTask:
    task_id: str
    entry_point: str
    prompt: str                    # complete_prompt 그대로
    libs: List[str]
    doctest_src: str               # doc_struct examples 를 이어 붙인 doctest 텍스트 ('' 이면 예제 없음)
    n_examples_with_output: int
    static_screen: List[str]       # 정적 스크린에 걸린 토큰 (비어 있으면 통과)
    _canonical: str = field(repr=False, default="")
    _test: str = field(repr=False, default="")
    meta: Dict[str, Any] = field(default_factory=dict)

    def visible_tests(self) -> List[str]:
        """가시 테스트 = doctest 블록 1개를 TestCases 모듈로 (공식 untrusted_check 로 판정). 적격성 통과 과제에서만 쓴다."""
        if not self.doctest_src:
            return []
        return [_doctest_snippet(self.doctest_src, self.task_id)]

    def spec(self, visible: bool) -> Dict[str, Any]:
        """visible=True 면 가시 테스트를 tests 에 넣는다(적격성 통과 과제만). hidden_tests 는 공식 test 모듈 (kind bcb 전용)."""
        return {"kind": "bcb", "entry_point": self.entry_point, "tests": self.visible_tests() if visible else [],
                "hidden_tests": [self._test], "hidden_exposed": False}


def _doctest_snippet(src: str, name: str) -> str:
    """doctest 블록 → unittest TestCases 모듈. 공식 untrusted_check 가 code + test 를 한 모듈로 exec 하므로 globals() 에 후보 정의가 있다."""
    return ("import unittest as _ut\nimport doctest as _dt\n"
            "class TestCases(_ut.TestCase):\n"
            "    def test_doctest(self):\n"
            f"        _t = _dt.DocTestParser().get_doctest({src!r}, dict(globals()), {name!r}, None, 0)\n"
            "        _r = _dt.DocTestRunner(verbose=False, optionflags=_dt.NORMALIZE_WHITESPACE | _dt.ELLIPSIS).run(_t, out=lambda s: None)\n"
            "        self.assertEqual(_r.failed, 0, 'doctest failed %d/%d' % (_r.failed, _r.attempted))\n")


def _download() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = DATA_DIR / Path(BCB_FILE).name
    if not p.exists():
        url = f"https://huggingface.co/datasets/{BCB_REPO}/resolve/{BCB_REVISION}/{BCB_FILE}"
        print(f"[bcb] downloading {url}")
        urllib.request.urlretrieve(url, p)
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != BCB_SHA256:
        raise RuntimeError(f"[bcb] 데이터 sha256 불일치: {h} != {BCB_SHA256} ({p})")
    return p


def load_bcb(ids: Optional[List[str]] = None) -> List[BcbTask]:
    df = pd.read_parquet(_download())
    tasks = []
    for _, r in df.iterrows():
        if ids is not None and r["task_id"] not in ids:
            continue
        ds = json.loads(r["doc_struct"])
        src = "\n".join(ds.get("examples", []))
        exs = doctest.DocTestParser().get_examples(src) if src else []
        n_out = sum(bool(e.want.strip()) for e in exs)
        hits = sorted({m.group(0) for m in _NONDET_RE.finditer(src)})
        tasks.append(BcbTask(r["task_id"], r["entry_point"], r["complete_prompt"], list(ast.literal_eval(r["libs"])),
                             src if n_out else "", n_out, hits, _canonical=r["canonical_solution"], _test=r["test"],
                             meta={"revision": BCB_REVISION, "file": BCB_FILE}))
    return tasks


if __name__ == "__main__":
    ts = load_bcb()
    n_cand = sum(bool(t.doctest_src) for t in ts)
    n_clean = sum(bool(t.doctest_src) and not t.static_screen for t in ts)
    print(f"tasks={len(ts)} with_doctest_output={n_cand} static_screen_clean={n_clean}")
    t = ts[0]
    assert t._test not in t.prompt and t._canonical not in t.prompt and "hidden" not in t.spec(True)["tests"][0]
    print(t.task_id, t.libs, t.static_screen, t.visible_tests()[0][:120])
    print("bcb.py self-check OK")
