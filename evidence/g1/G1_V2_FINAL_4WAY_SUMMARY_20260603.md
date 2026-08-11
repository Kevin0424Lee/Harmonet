# HarmoNet v2 Final G1 4-way Verification - 2026-06-03

Scope: HumanEval 20 + MBPP 20, 3 repeats each, RunYourAI model anthropic/claude-haiku-4-5.

| System | Runs | Pass rate | Avg tokens | Avg latency | p99 latency | Failures |
|---|---:|---:|---:|---:|---:|---:|
| harmonet_v2 | 120 | 100.0% | 224.4 | 2.223s | 5.603s | 0 |
| langraph_runyourai_anthropic_claude_haiku_4_5 | 120 | 95.8% | 1790.6 | 9.128s | 14.558s | 5 |
| autogen_anthropic_claude_haiku_4_5 | 120 | 100.0% | 814.5 | 5.631s | 9.101s | 0 |
| crewai_anthropic_claude_haiku_4_5 | 120 | 99.2% | 295.0 | 6.156s | 8.257s | 1 |

## Failure Details

- harmonet_v2: none
- langraph_runyourai_anthropic_claude_haiku_4_5: humaneval HumanEval/16 r1, humaneval HumanEval/16 r2, humaneval HumanEval/16 r3, mbpp mbpp_2 r2, mbpp mbpp_7 r1
- autogen_anthropic_claude_haiku_4_5: none
- crewai_anthropic_claude_haiku_4_5: humaneval HumanEval/16 r2

## Interpretation

- HarmoNet v2 is the only framework that is both 100% passing and under 300 average tokens in this final 4-way run.
- AutoGen also reached 100% pass rate, but used about 3.6x more tokens and about 2.5x higher average latency than HarmoNet v2.
- CrewAI used similar token volume to HarmoNet v2 but had one failure and substantially higher latency.
- LangGraph had the highest token cost and five failures in this run.
