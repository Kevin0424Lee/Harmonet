"""
scripts/check_submission.py — 제출 빌드 전 점검: DRAFT 표시·TODO·미완료 표시·절대 경로·run id·git 원격·저자명이 원고/참고문헌에 남아 있으면 실패.
    python -X utf8 scripts/check_submission.py paper/main.tex paper/main.bib
"""
import re
import sys
from pathlib import Path

DRAFTNOTE = "\\draftnote{"                                 # 리터럴 (매크로 정의 줄은 제외)
DRAFTMODE = "\\draftmodetrue"
PATTERNS = [r"\bDRAFT\b", r"\bTODO\b", r"\bTBD\b", r"C:\\Users", r"/Users/", r"Kevin0424Lee", r"Harmonet\.git",
            r"pilot_explore\b", r"pilot_confirm\b", r"leeeungyu", r"github\.com/(?!anonymous)"]


def main(paths) -> int:
    bad = 0
    for p in paths:
        for i, line in enumerate(Path(p).read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("%"):
                continue
            hits = []
            if DRAFTNOTE in line and "newcommand" not in line:
                hits.append("draftnote")
            if DRAFTMODE in line and "newif" not in line and "newcommand" not in line:
                hits.append("draftmodetrue")
            hits += [pat for pat in PATTERNS if re.search(pat, line)]
            for h in hits:
                print(f"{p}:{i}: {h}: {line.strip()[:100]}")
                bad += 1
    print("OK — 제출 빌드 가능" if not bad else f"{bad} 건 — 제출 불가")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
