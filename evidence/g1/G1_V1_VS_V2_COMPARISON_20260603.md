# HarmoNet v1 vs v2 G1 Comparison - 2026-06-03

Scope: HumanEval 20 + MBPP 20, 3 repeats each, RunYourAI model anthropic/claude-haiku-4-5.

| System | Runs | Pass rate | Avg tokens | Avg latency | p99 latency |
|---|---:|---:|---:|---:|---:|
| HarmoNet v1 | 120 | 100.0% | 488.4 | 7.294s | 11.364s |
| HarmoNet v2 | 120 | 100.0% | 224.4 | 2.223s | 5.603s |

## Delta

| Metric | v2 vs v1 |
|---|---:|
| Token reduction | 54.1% lower |
| Average latency reduction | 69.5% lower |
| p99 latency reduction | 50.7% lower |
| Success rate change | 0.0pp |

## By Benchmark

| Benchmark | v1 pass | v1 tokens | v1 latency | v2 pass | v2 tokens | v2 latency |
|---|---:|---:|---:|---:|---:|---:|
| HumanEval | 100.0% | 510.3 | 7.216s | 100.0% | 198.1 | 1.842s |
| MBPP | 100.0% | 466.6 | 7.372s | 100.0% | 250.8 | 2.603s |

Interpretation: v2 preserves the v1 pass rate while cutting token use and latency substantially. The largest gain is on HumanEval, where v2 uses about 61% fewer tokens and is about 74% faster on average.
