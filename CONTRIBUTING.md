# Contributing

This repository is intended to keep experiments reproducible and easy to audit.

Before opening a pull request:

1. Run `python -m pytest tests/ -x -q`.
2. Keep benchmark results under `evidence/` only when they are summarized and do
   not contain API keys or raw private prompts.
3. Prefer small, reviewable changes over broad rewrites.
4. Document benchmark commands and environment assumptions when results change.
