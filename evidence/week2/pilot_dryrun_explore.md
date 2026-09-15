# 파일럿 보고 — explore (mock-scenario, run_id=pilot_explore, N=4, 510s)

- 실효 설정(env, 단일 출처 = pilot_config_v4.json): {"HARMONET_BCB_IMAGE": "bigcodebench/bigcodebench-evaluate@sha256:a3cd34ec3840a49d6b7afb240f4bdd47c350bc5991043fd0a91773830f7cd405", "HARMONET_BCB_TIMEOUT_S": "241.0", "HARMONET_BCB_MARGIN_S": "90", "ANTHROPIC_MAX_TOKENS": "4096", "ANTHROPIC_TEMPERATURE": "0.2", "HARMONET_BUDGET_CAP": "16.0", "HARMONET_BUDGET_ID": "pilot_v4", "HARMONET_MODEL_BUILDER": "claude-haiku-4-5", "HARMONET_MODEL_REVIEWER": "claude-sonnet-4-6"}
- 풀 관문: 최고 arm B-expert 75.0% (문턱 80%) → **진행**
- 0회차: b_cont $0.0087, a_call_median $0.0029 (n=2)
- 탐색 CV(모델 선택용): λ*=0.3, 특징 18열, P2-post +25.0pp CI [0.0, 0.3333333333333333], P2-pre +25.0pp, P1 +0.0pp; 순열 p(진단) 0.849
- 동결: â=B-expert, sha256 5f9b609c5b6a, 커밋 해시 (동결 커밋 뒤 PREREG 에 기입)
- 뒤집힘: {"A-self": {"n_cells": 2, "flip_rate": 0.0}, "B-expert": {"n_cells": 2, "flip_rate": 0.0}}

| arm | 히든 성공률 | 거부율 | arm 단독 $ | 호출 수 평균 |
|---|---|---|---|---|
| T | 25.0% | 0% | $0.0 | 0.0 |
| A-self | 50.0% | 0% | $0.0116 | 1.0 |
| A-selfxk | 25.0% | 0% | $0.0087 | 0.8 |
| A-role | 50.0% | 0% | $0.0116 | 1.0 |
| B-expert | 75.0% | 0% | $0.0348 | 1.0 |
| B-solo | 50.0% | 0% | $0.0348 | 1.0 |

- 총지출(원장 29 호출): $0.1537 = 앞 단계 $0.0 + 0회차 $0.0174 + arm $0.1247 + 여기서 만든 s0 $0.0116 + 미완료 arm $0 (0건) (가져온 s0 원 생성비, 역사적 $0.0; 미측정 0; arm 실측 $0.1247 / 불명 귀속 $0.0; 검산 ledger == prior + round0 + Σ arms_own + s0_built_here + incomplete)
- 중단 사유: None
