# 파일럿 보고 — confirm (mock-scenario, run_id=pilot_confirm, N=2, 118s)

- 실효 설정(env, 단일 출처 = pilot_config_v4.json): {"HARMONET_BCB_IMAGE": "bigcodebench/bigcodebench-evaluate@sha256:a3cd34ec3840a49d6b7afb240f4bdd47c350bc5991043fd0a91773830f7cd405", "HARMONET_BCB_TIMEOUT_S": "241.0", "HARMONET_BCB_MARGIN_S": "90", "HARMONET_BCB_MEMORY": "8g", "HARMONET_BCB_CPUS": "2", "HARMONET_BCB_LIMITS": "{\"gt_time_limit\": 1.0, \"max_as_limit\": 30720, \"max_data_limit\": 30720, \"max_stack_limit\": 10, \"min_time_limit\": 1.0}", "ANTHROPIC_MAX_TOKENS": "4096", "ANTHROPIC_TEMPERATURE": "0.2", "HARMONET_BUDGET_CAP": "16.0", "HARMONET_BUDGET_ID": "pilot_v4", "HARMONET_PILOT_CONFIG_SHA256": "ffdc7bd1de7ba0c7e2541fbc3a53829e024fcbd4d926a9531337647dcc6cc3b5", "HARMONET_MODEL_BUILDER": "claude-haiku-4-5", "HARMONET_MODEL_REVIEWER": "claude-sonnet-4-6", "_effective_docker": {"resources": {"memory": "8g", "cpus": "2"}, "limits": {"max_as_limit": 30720, "max_data_limit": 30720, "max_stack_limit": 10, "min_time_limit": 1.0, "gt_time_limit": 1.0}, "container_args": ["--network", "none", "--memory", "8g", "--cpus", "2", "-v", "/w:/w", "-w", "/w", "--entrypoint", "python3", "bigcodebench/bigcodebench-evaluate@sha256:a3cd34ec3840a49d6b7afb240f4bdd47c350bc5991043fd0a91773830f7cd405", "-I", "harness.py"]}}
## 판정: **미확인** — 평균 d = +50.0pp (b=1, c=0, McNemar 단측 p=0.5000, CI95 [0.0, 100.0]); 정확 McNemar 단측 p < 0.05 ∧ 평균 d ≥ 0.10 (양의 이득 증거 + 점추정의 실용 문턱; '≥10% 입증' 아님)
- 부차: post−pre +50.0pp (p 0.500); P2-pre vs â +0.0pp; P1 vs â +50.0pp; oracle(기술) 50.0pp
- 정책 선택 분포: T 0%, A-self 0%, A-selfxk 0%, A-role 50%, B-expert 50%, B-solo 0%; arm 만: 정책 $0.0058 / 고정 $0.0087; 배포(정책 = arm + s0 $0.0029): 정책 $0.0087 / 고정 B-expert $0.0116(+s0) (과제당)

| arm | 히든 성공률 | 거부율 | arm 단독 $ | 호출 수 평균 |
|---|---|---|---|---|
| T | 50.0% | 0% | $0.0 | 0.0 |
| A-self | 0.0% | 0% | $0.0058 | 1.0 |
| A-selfxk | 50.0% | 0% | $0.0029 | 0.5 |
| A-role | 50.0% | 0% | $0.0058 | 1.0 |
| B-expert | 0.0% | 0% | $0.0174 | 1.0 |
| B-solo | 50.0% | 0% | $0.0174 | 1.0 |

- 총지출(원장 40 호출): $0.2088 = 앞 단계 $0.1537 + 0회차 $0.0 + arm $0.0493 + 여기서 만든 s0 $0.0058 + 미완료 arm $0 (0건) (가져온 s0 원 생성비, 역사적 $0.0; 미측정 0; arm 실측 $0.0493 / 불명 귀속 $0.0; 검산 ledger == prior + round0 + Σ arms_own + s0_built_here + incomplete)
- 중단 사유: None
