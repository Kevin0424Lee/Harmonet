# arms 스모크 F1-b (실제 Docker, 시나리오 mock, 유료 0) — arms_smoke_f1

3 과제 × 6 arm × k=2 = 36 행. 기대 일치 36/36, eval:hidden 0, 모든 행 hidden level=functional·sandbox=docker·exec_count≥1.
비용: arm 단독 합 $0.243 + shared_s0 $0.0405 = 총지출 $0.2835 (가격표 이름만 빌린 mock 토큰, 실제 지출 0).

| task | arm | rep | level | sandbox | exec_count | hidden | 기대 | n_calls | models | cost_usd |
|---|---|---|---|---|---|---|---|---|---|---|
| BigCodeBench/3 | B-solo | 1 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/3 | B-expert | 1 | functional | docker | 1 | True | True | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/3 | T | 1 | functional | docker | 1 | False | False | 0 |  | 0.0 |
| BigCodeBench/3 | A-self | 1 | functional | docker | 1 | True | True | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/3 | A-role | 1 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/3 | A-selfxk | 1 | functional | docker | 1 | False | False | 0 |  | 0.0 |
| BigCodeBench/3 | B-solo | 2 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/3 | B-expert | 2 | functional | docker | 1 | True | True | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/3 | T | 2 | functional | docker | 1 | False | False | 0 |  | 0.0 |
| BigCodeBench/3 | A-self | 2 | functional | docker | 1 | True | True | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/3 | A-role | 2 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/3 | A-selfxk | 2 | functional | docker | 1 | False | False | 0 |  | 0.0 |
| BigCodeBench/4 | T | 1 | functional | docker | 1 | False | False | 0 |  | 0.0 |
| BigCodeBench/4 | A-self | 1 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/4 | B-solo | 1 | functional | docker | 1 | True | True | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/4 | B-expert | 1 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/4 | A-role | 1 | functional | docker | 1 | True | True | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/4 | A-selfxk | 1 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/4 | T | 2 | functional | docker | 1 | False | False | 0 |  | 0.0 |
| BigCodeBench/4 | A-self | 2 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/4 | B-solo | 2 | functional | docker | 1 | True | True | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/4 | B-expert | 2 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/4 | A-role | 2 | functional | docker | 1 | True | True | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/4 | A-selfxk | 2 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/9 | B-expert | 1 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/9 | A-selfxk | 1 | functional | docker | 1 | True | True | 0 |  | 0.0 |
| BigCodeBench/9 | A-self | 1 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/9 | B-solo | 1 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/9 | T | 1 | functional | docker | 1 | True | True | 0 |  | 0.0 |
| BigCodeBench/9 | A-role | 1 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/9 | B-expert | 2 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/9 | A-selfxk | 2 | functional | docker | 1 | True | True | 0 |  | 0.0 |
| BigCodeBench/9 | A-self | 2 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
| BigCodeBench/9 | B-solo | 2 | functional | docker | 1 | False | False | 1 | claude-haiku-4-5 | 0.0045 |
| BigCodeBench/9 | T | 2 | functional | docker | 1 | True | True | 0 |  | 0.0 |
| BigCodeBench/9 | A-role | 2 | functional | docker | 1 | False | False | 1 | claude-sonnet-4-6 | 0.0135 |
