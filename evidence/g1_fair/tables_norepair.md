### 신 측정 — 수리 제외

| system | n | pass rate | avg prompt | avg completion | avg total | sd total | vs LangGraph | token_source |
|---|---|---|---|---|---|---|---|---|
| harmonet_v2 | 120 | 92.5% | 171 | 103 | 274 | 95 | 78.5% less | measured |
| langraph | 120 | 91.7% | 696 | 581 | 1277 | 356 | (base) | measured |
| autogen | 120 | 94.2% | 621 | 231 | 852 | 301 | 33.3% less | measured |
| crewai | 120 | 95.0% | 772 | 208 | 980 | 251 | 23.2% less | measured |

| system | HumanEval pass | HumanEval tokens | MBPP pass | MBPP tokens |
|---|---|---|---|---|
| harmonet_v2 | 95.0% | 300 | 90.0% | 248 |
| langraph | 90.0% | 1391 | 93.3% | 1163 |
| autogen | 95.0% | 1043 | 93.3% | 661 |
| crewai | 95.0% | 1122 | 95.0% | 839 |

