# paper/ — ICLR 2027 submission draft (HarmoNet fair-measurement branch)

- Template: official `iclr-2027-style-files.zip` (downloaded 2026-09-15 from https://media.iclr.cc/Conferences/ICLR2027/iclr-2027-style-files.zip), unpacked in `iclr2027/`; the `.sty/.bst/math_commands.tex` copies at top level are what `main.tex` uses.
- Deadlines (ICLR 2027 CFP/Author Guidelines, checked 2026-09-15): abstract registration **Sep 18, 2026 11:59 PM AoE** (= **Sep 19 20:59 KST**); full paper **Sep 25, 2026 11:59 PM AoE** (= **Sep 26 20:59 KST**).
  No authors can be added or removed after the abstract deadline (order can change until the full deadline). Main text ≤ 9 pages (10 at camera-ready); references/appendix unlimited.
  Double blind; author identity anywhere in main text or supplementary → desk reject. Every submission needs ≥1 author registered to review ≥3 papers; authors on ≥3 papers review ≥6.
  Mandatory **AI use statement** (not counted); reproducibility statement encouraged (not counted). AI Policy for Authors: authors are responsible for AI-produced falsehoods/plagiarism.
- Build (draft): `pdflatex main && bibtex main && pdflatex main && pdflatex main` (no LaTeX toolchain on this machine as of 2026-09-15 — see decision package).
- Build (submission): set `\draftmodefalse` in `main.tex`; any remaining `\draftnote` aborts the build; also run `python scripts/check_submission.py paper/main.tex paper/main.bib` (fails on DRAFT markers, TODOs, absolute paths, run ids, git remotes).
- Tables/figures are generated from `evidence/week2/*` by `paper/make_tables.py` (to be written once exploration artifacts exist) — never typed by hand.
