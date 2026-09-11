### 구 측정

| system | n | pass rate | avg prompt | avg completion | avg total | sd total | vs LangGraph | token_source |
|---|---|---|---|---|---|---|---|---|
| harmonet_v2 | 120 | 100.0% | 102 | 122 | 224 | 109 | 87.5% less | (none — 구 CSV, 자체 집계) |
| langraph | 120 | 95.8% | 879 | 912 | 1791 | 419 | (base) | (none — 구 CSV, 자체 집계) |
| autogen | 120 | 100.0% | 538 | 276 | 814 | 296 | 54.5% less | (none — 구 CSV, 자체 집계) |
| crewai | 120 | 99.2% | 231 | 64 | 295 | 103 | 83.5% less | (none — 구 CSV, 자체 집계) |

| system | HumanEval pass | HumanEval tokens | MBPP pass | MBPP tokens |
|---|---|---|---|---|
| harmonet_v2 | 100.0% | 198 | 100.0% | 251 |
| langraph | 95.0% | 1758 | 96.7% | 1823 |
| autogen | 100.0% | 860 | 100.0% | 769 |
| crewai | 98.3% | 356 | 100.0% | 234 |

### 신 측정 — 수리 포함

| system | n | pass rate | avg prompt | avg completion | avg total | sd total | vs LangGraph | token_source |
|---|---|---|---|---|---|---|---|---|
| harmonet | 120 | 92.5% | 197 | 84 | 281 | 75 | 78.0% less | measured |
| harmonet_v2 | 120 | 92.5% | 204 | 109 | 313 | 196 | 75.5% less | measured |
| langraph | 120 | 93.3% | 696 | 583 | 1278 | 337 | (base) | measured |
| autogen | 120 | 94.2% | 621 | 230 | 852 | 295 | 33.4% less | measured |
| crewai | 120 | 95.0% | 778 | 217 | 995 | 282 | 22.1% less | measured |

| system | HumanEval pass | HumanEval tokens | MBPP pass | MBPP tokens |
|---|---|---|---|---|
| harmonet | 90.0% | 331 | 95.0% | 230 |
| harmonet_v2 | 95.0% | 328 | 90.0% | 299 |
| langraph | 93.3% | 1369 | 93.3% | 1187 |
| autogen | 95.0% | 1032 | 93.3% | 671 |
| crewai | 95.0% | 1154 | 95.0% | 837 |

