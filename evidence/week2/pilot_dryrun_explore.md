# 파일럿 보고 — explore (mock-scenario, run_id=pilot_explore, N=4, 391s)

- 풀 관문: 최고 arm B-expert 75.0% (문턱 80%) → **진행**
- 0회차: b_cont $0.0087, a_call_median $0.0029 (n=2)
- 탐색 CV(모델 선택용): λ*=0.3, 특징 18열, P2-post +25.0pp CI [0.0, 0.3333333333333333], P2-pre +25.0pp, P1 +0.0pp; 순열 p(진단) 0.849
- 동결: â=B-expert, sha256 bd83d95c37f6, 커밋 해시 (동결 커밋 뒤 PREREG 에 기입)
- 뒤집힘: {"A-self": {"n_cells": 2, "flip_rate": 0.0}, "B-expert": {"n_cells": 2, "flip_rate": 0.0}}

| arm | 히든 성공률 | 거부율 | arm 단독 $ | 호출 수 평균 |
|---|---|---|---|---|
| T | 25.0% | 0% | $0.0 | 0.0 |
| A-self | 50.0% | 0% | $0.0116 | 1.0 |
| A-selfxk | 25.0% | 0% | $0.0087 | 0.8 |
| A-role | 50.0% | 0% | $0.0116 | 1.0 |
| B-expert | 75.0% | 0% | $0.0348 | 1.0 |
| B-solo | 50.0% | 0% | $0.0348 | 1.0 |

- 총지출(원장 29 호출): $0.1537 = 앞 단계 $0.0 + 0회차 $0.0174 + arm $0.1247 + 여기서 만든 s0 $0.0116 (가져온 s0 원 생성비, 역사적 $0.0; 미측정 0; 검산 ledger == prior + round0 + Σ arms_own + s0_built_here)
- 중단 사유: None
