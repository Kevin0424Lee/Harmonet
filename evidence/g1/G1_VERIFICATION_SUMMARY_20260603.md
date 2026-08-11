# HarmoNet v2 G1 Verification - 2026-06-03

Scope: HumanEval 20 + MBPP 20, 3 repeats each, RunYourAI model anthropic/claude-haiku-4-5.

## Valid results

| System | Runs | Pass rate | Avg tokens | Avg latency | p99 latency |
|---|---:|---:|---:|---:|---:|
| HarmoNet v2 + eval repair | 120 | 100.0% | 229.5 | 2.242s | 4.508s |
| CrewAI | 120 | 97.5% | 295.2 | 6.537s | 17.136s |

## Notes

- HarmoNet v2 used the evaluator-aware repair path once: MBPP mbpp_7 repeat 3. The repaired result passed.
- CrewAI failed 3/120 cases: HumanEval/16 repeat 2, HumanEval/16 repeat 3, MBPP mbpp_9 repeat 2.
- Earlier CrewAI 0% output from Python 3.14 .venv was invalid because the crewai module was not installed there. This run used .venv-crewai with CrewAI 1.14.6.
- API key literal was not found in the produced result artifacts.

## Artifacts

- g1_harmonet_v2_repair_20x3.json / csv / report / log
- g1_crewai_20x3_venvcrewai.json / csv / report / log
