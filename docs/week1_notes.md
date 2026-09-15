# Week 1 진행 메모 — Part C 설계에 반영할 항목

Part A 진행 중 확정된 사실과, 2주차 설계(`docs/week2_design_draft.md`)에 넣어야 할 항목의 누적 목록.

## Part C "실행 환경" 항목
- `evidence/*/run_*.ps1` 등 기존 실행 스크립트는 A2 이후 `HARMONET_ALLOW_NO_REDIS=1` 없이는 즉시 `RuntimeError`.
  재실행 시 반드시 추가. Mock 은 `HARMONET_LLM_BACKEND=mock` 명시 필요 (자동 폴백 없음).
- legacy 메커니즘(Kuramoto·TDA·SOC)은 `HARMONET_LEGACY_MECHANISMS=1` 일 때만. 기본 실행은 코사인 + 적응형 δ 게이트.

## Part C 공정성 항목
- `benchmark/agents_harmonet_v2.py:repair_after_eval` 는 외부 채점기의 실패 출력(`eval_error`, 히든 테스트 결과)을
  프롬프트에 넣는다 — N3 와 같은 누출 패턴. A4c 부터 **기본 차단** (`G1_DISABLE_EVAL_REPAIR` 기본 1, 켜려면 `=0` 명시) 이고 켜서 실행하면 trace 에 `trigger=eval:hidden`, `TaskState.leak_risk=true` 라벨.
- v1 어댑터의 키워드 기반 repair 경로(`benchmark/agents_harmonet.py`, `HARMONET_REPAIR_KEYWORD_THRESHOLD`)는
  HarmoNet 에만 있는 2차 LLM 호출. 조건 간 비교 시 끄거나 전 조건에 동일 적용.

## Part C 전제 조건 (2주차 첫 작업)
- validator 가 실행할 **공개** 테스트: HumanEval docstring 의 `>>>` 예제를 doctest 로 추출해 `task_spec["tests"]` 에 넣는다.
  현재 G1 러너는 채점용 히든 테스트를 넣지 않으므로(누출 방지) validator 는 AST + 진입점 검사까지만 수행.

## A1~A3 관찰 기록
- Architect 오배송 (정정): A0 에서 architect 가 builder 피드백 씨앗에 공명하는 것을 봤고 "실행"으로 보고했으나,
  실행은 아니었다(당시 호출 수 Architect 0). A3 후 재현: `target_role` 필터를 끄고 피드백 문구를 A0 당시
  "Security validation required: FastAPI JWT … OWASP audit" 로 되돌리면 **3/3 회 architect 공명**(유사도 0.636 > δ 0.20),
  단 claim 우선순위 지연이 유사도 기반이라 validator(0.835, 8ms)가 항상 먼저 선점하고 architect(18ms)는 스킵.
  결론: **코사인 게이팅은 씨앗 문구에 민감하다. 검증 요청을 보안 감사처럼 쓰면 Architect(sim 0.636)로 오배송된다.**
  비결정성은 없었다(Kuramoto on/off, 필터 on/off 모두 반복 동일). 현재는 `target_role` 로 구조 차단.
  주 경로의 마지막 난수 원천(감지기 초기 위상, `resonance.py:71`)은 legacy 가 아닐 때 0 으로 고정.
- validator 결과 씨앗의 `verification` off-by-one → A4 에서 판정을 인자로 직접 전달해 수정 (`agent.py:_scatter_feedback_seed(…, verification)`).

## Part C 지연 측정 항목
- `benchmark/agents_harmonet.py` 와 데모는 legacy 플래그가 없어도 `KuraMotoCoupler.step()` / `sync_phase()` 를 매 틱 호출한다
  (에이전트는 무시). 지연시간 비교에 이 낭비 연산이 섞이지 않게 v1 어댑터에서 제거하거나 측정에서 분리.

## A4 trace 비용 귀속 규칙 (v1 어댑터)
- v1 은 세 에이전트가 같은 틱에서 동시에 도는 구조라 METER 델타를 호출 단위로 분리할 수 없다. 틱 단위 델타를 그 틱의
  builder 행동에 귀속하고 나머지 LLM 행동은 0 으로 기록한다. 2주차 비교(단일 vs 자기수정 vs 전문가)는 v2/single 처럼
  호출이 직렬인 어댑터로 하는 것이 안전하다.

## A5 관찰
- LLM 역할은 코드에 두 개뿐: `builder`(build/self_revise/eval_repair 호출), `reviewer`(v2 의 LLM validator = expert_review).
  `AgentRole` 의 architect/validator/observer 는 v1 필드 역할이지 LLM 역할이 아니다 → `get_llm_client("architect")` 는 ValueError.
  v1 어댑터는 `get_llm_client()`(기본, role="default") 그대로 — 비용 귀속도 tick_aggregate 유지.
- v2 의 reviewer 단계는 **open-ended 과제(api_design 등)에서만** 돈다. HumanEval/MBPP 같은 실행 가능 코드 과제는
  builder-only 이므로 2주차 "전문가 추가" 조건은 v2 프로파일 로직을 우회해 명시적으로 호출해야 한다.
- 지정 모델 존재 확인은 무료 조회로 한다: Ollama `/api/tags`, OpenAI/호환/Anthropic `models.retrieve`. 지정하지 않은 역할(기본 모델)은
  조회를 생략한다 (기존 G1 실행 흐름을 바꾸지 않기 위해).
- `Action.model` 은 실백엔드에서 `response.model` (Ollama /v1 실측: `qwen2.5-coder:7b`), mock 은 설정명 echo (`mock-a`).

## A7 검증기 한계 (subprocess 샌드박스)
- **(A7b 정정)** A7 보고의 "argv 위조도 nonce 불일치로 aborted" 는 그 테스트가 'forged' 라는 틀린 nonce 를 썼기 때문에
  통과한 것이었다. A7b 이전(134f264)에는 `sys.argv[1]` 의 nonce 로 정확히 위조하는 후보와 `sys.modules['json'].dump` 를
  패치하는 후보가 **passed=True** 였고, 정답 + non-daemon 스레드는 timeout(거짓 실패)이었다 (Fable 재현, 2026-09-13,
  `tests/test_verify_probe8.py` 로 이 세션에서도 3/8 실패 재현). A7b: nonce·경로를 stdin 으로, 기록기 사전 바인딩, 종료 시 os._exit.
- 종료 코드·stdout 은 통과 신호가 아니다. 하네스의 result.json(nonce) 만 본다. `passed=True` 는 level=functional 뿐이라
  **공개 테스트가 없는 과제(현재 G1 러너, `tests: None`)에서는 validator 판정이 항상 `no_tests`/passed=False** 다 —
  doctest 추출(2주차 첫 작업)이 전제인 이유.
- subprocess 모드는 같은 OS 사용자 권한, 파일시스템·네트워크 격리 없음, CPU/메모리 제한 없음(타임아웃만).
  argv/env 를 읽어 nonce 를 위조하는 고의적 후보는 범위 밖. `HARMONET_SANDBOX=docker` 는 python:3.11-slim,
  `--network none`; Docker 없으면 RuntimeError. Docker 모드는 아직 실측 실행하지 않음(이미지 pull 필요).
- v2 의 정적 검사(`_cheap_validate`)도 level=static 이라 passed=False. v2 가 "accepted" 로 삼는 기준은 outcome 뿐.

## A7c 공개/히든 분리 · EvalPlus 확인
- HumanEval: 공개 = docstring `>>>` doctest → `spec["tests"]` (첫 20개 과제 모두 1~3개 존재), 히든 = `check(entry_point)` 프로그램 1건.
- MBPP: `test_list` 가 프롬프트에 노출 → **히든 없음**. 러너는 대조·기록을 위해 같은 test_list 로 채점하되 `hidden_exposed=True` 로 표시.
  히든 점수로 인용 금지. 공개 검증용으로만.
- EvalPlus 0.3.1 (`pip download` 로 휠만 확인, 미설치): 과제마다 `base_input`(원본 테스트 입력) 과 `plus_input`(추가 생성 입력) 이
  **분리**돼 있고 기대 출력은 저장돼 있지 않아 `canonical_solution` 실행으로 얻는다(evalplus 자체 평가기가 수행). 따라서 plus_input 은
  프롬프트에 없는 히든 테스트로 채택 가능. 비용: `pip install evalplus`(numpy·tqdm·wget 등), HumanEval+ v0.1.10 / MBPP+ v0.2.0 캐시 다운로드(수 MB),
  기대 출력 생성용 canonical 실행 1회. **보류 사유: 이번 작업 범위를 좁히기 위해.** LCB 가 모든 층에서 부적격일 때의 예정된 대안. 채택은 승인 후.
- 재채점 대조: 거짓 통과 0/360. v1 산출물은 120/120 `heuristic` 추출(코드 블록 없이 출력) — 채점엔 문제 없었으나 2주차 arm 에서는 fenced 를 요구할 것.

## 검토 오류 기록 (2026-09-13, 코덱스 지적으로 발견)
| 누가 | 무엇을 틀렸나 | 근거 파일 |
|---|---|---|
| Fable | C2 §0 "최선 고정 = REDEREF 사후분포가 수렴하는 정책" 주장 — REDEREF 원문을 확인하지 않고 씀. REDEREF 는 질의 유사도·시간 감쇠로 사전분포를 두고 판정 결과로 재라우팅·종료한다 | `docs/week2_design_draft.md` §0 (C3 에서 정정), `docs/related_work_week1.md` REDEREF 행 |
| Fable | 교수님 문서에서 SWE 11/30 을 HarmoNet 수치로 오기 — 실제는 single_validate(single + apply-check 수리) | `evidence/swe_fair/haiku_0_30_4k_nohints/README.md` |
| Fable | v1 토큰 434 를 2차 통과율 옆에 배치해 같은 조건처럼 읽히게 함 | `evidence/g1_fair/rerun/README.md` |
| Fable | "힌트 빼면 25%" 를 인과로 서술 — README 는 hints 유무를 통제한 비교가 아님(모델·max_tokens 도 함께 바뀜) | `evidence/swe_fair/haiku_0_30_4k_nohints/README.md` |
| Claude Code | A7 보고 "argv 위조도 nonce 불일치로 aborted" — 테스트가 'forged' 라는 틀린 nonce 를 써서 통과한 것. 실제로는 argv 를 읽는 후보가 passed=True 였음 | `tests/test_verify_probe8.py` (A7b), 이 파일 A7 항목 |
| Claude Code | A7 에서 verify 함수만 고치고 러너(`external_g1.py`)의 채점 호출처는 연결하지 않아 옛 종료 코드 채점기가 그대로 쓰임 | A7c 커밋 `d7f429a` 이전의 `benchmark/external_g1.py:evaluate_code` |
| Fable | stdio 하네스 규칙 "출력 완료 시점 기준 pass + kill" — 정답 출력 후 RuntimeError/무한루프가 pass 로 판정됨 (코덱스 재현). A0c 에서 rc==0 ∧ 정상 종료 규칙으로 교체 | `harmonet/verify.py` stdio docstring, `tests/test_verify_stdio_adversarial.py` |
| Fable | C3 §4 "참값은 보수적 gap 과 낙관적 gap 사이" — 근거 없는 괄호 주장. A0c 에서 삭제, 판정은 통과/미확인 둘로 | `docs/week2_design_draft.md` §4 |
| Claude Code | HumanEval+ 제외 사유를 "천장(96.3%)"으로 씀 — 96.3% 는 HumanEval 결과이고 HumanEval+ 제외 사유는 164개 표본 조건 미달 | `evidence/week2/pool_probe.md` (A0c 정정) |
| Claude Code | 노출 가드가 True 로 해석되지 않는 값을 전부 False 로 취급 — `{"hidden_exposed": "unknown"}` 이 히든 1.0 (코덱스 재현). A0c 에서 명시적 False 만 허용 | `benchmark/hidden_guard.py`, `tests/test_hidden_guard.py` |
| Fable | B 단독 상한 70% 를 유도 없이 A 창을 복사해 사전 등록함 (유도값은 80%: B 실패율 ≥ 2×MDE). 결과 뒤 문턱을 옮기지 않은 것은 맞으나 유래를 처음부터 적었어야 함 (2026-09-14, 코덱스 지적) | `evidence/week2/pool_probe.md` 프로브 4, `docs/week2_review_draft.md` §3-2 |
| Fable | 재검토 초안에서 "가시 신호가 약하다" 단정 — 조건부 표(가시 실패→히든 실패 A 9/12, B 5/6)를 보면 실패 예측력은 있음. D4 에서 표로 대체 | `docs/week2_review_draft.md` §3-4 |
| Fable | "규칙 변경 시 새 프로브 60 필수" — 과함. 프로브는 성공률 추정용이고 새로 추정할 양이 없으면 기존 60 은 탐색 자료로 두고 확인 자료에서 평가하면 됨 | `docs/week2_review_draft.md` §4 |
| Fable | BCB 채점 결과의 n_run 이 "모듈 호출 수"(항상 1)인 것을 확인하지 않고 실행 수처럼 읽음 | `evidence/week2/bcb_source.md`, D2 이전 `harmonet/bcb_harness.py` |
| Claude Code | BCB 하네스 n_run = 테스트 모듈 호출 수. 공식 untrusted_check 는 실행된 테스트 수를 검사하지 않으므로 TestCase.run 을 no-op 으로 바꾼 후보가 pass (코덱스 지적, D2 에서 재현·수정: expected_tests 클린 프로세스 계수 + testsRun 검사 + 사전 바인딩) | `harmonet/bcb_check.py`, `tests/test_bcb_adversarial.py` |
| Claude Code | 누적 예산을 강제하지 않음 — 사전 등록 "상한 $1" 이 코드 어디에도 없었고 사후 합산만 함. D1 에서 원장·예약·중단 | `harmonet/budget.py`, `benchmark/runloop.py` |
| Claude Code | 채점 인프라 장애(docker 데몬·이미지) 시에도 다음 모델 호출을 계속함 — 후보 원인 aborted 와 구분 없음. D1 에서 infra 플래그 + 사전 점검 + 즉시 중단 | `harmonet/verify.py` `_run_bcb_harness`, `benchmark/runloop.py` |
| Claude Code | 타임아웃 시 docker CLI 만 죽이고 컨테이너는 정리하지 않음 (Windows 에서는 CLI kill 로 파이프도 안 닫혀 컨테이너 종료까지 대기). D1 에서 named container + docker kill + rm -f | `harmonet/verify.py`, `tests/test_budget_runloop.py` |

| Fable | D5 스모크 보고("18 traces validate")를 exec_count 확인 없이 승인 — 실제는 정적 error 18/18, 이미지 안 채점 0건 (F1 에서 정정) | `evidence/week2/docker_verification.md`, `evidence/week2/arms_smoke_f1.md` |
| Fable | 규칙 전체 검정력 미확인 — CI 하한 조건만 보고 "점추정 ≥ 10pp" 를 합친 R1 의 통과율을 계산하지 않음 (F4 에서 전체 규칙으로) | `evidence/week2/gap_power.md`, `docs/week2_design_draft.md` §4 개정안 |
| Claude Code | D5 mock 이 코드가 아닌 문장을 내서 스모크가 채점기를 한 번도 거치지 않음 (무효 코드 mock) | `benchmark/mock_scenario.py` (F1-a) |
| Claude Code | D5 출력 스키마(tasks[].rows, passed)가 분석기 입력(hidden_pass, rep)과 불일치 — 그대로 넣으면 KeyError | `benchmark/arms.py` F1-d, `tests/test_arms.py::test_rows_feed_gap_analysis` |
| Claude Code | 반복 층 부재 — arm 을 k 회 반복할 저장 경로·멱등 재실행이 없었음 | `benchmark/arms.py` F1-c (`<task>/<arm>/rep<r>/`) |
| Claude Code | arm 내부에서 infra=True 여도 다음 verify·호출을 계속함 (테스트: s0 인프라 장애 뒤 6회 호출) | `benchmark/arms.py` F1-e (InfraStop) |
| Claude Code | s0 build 비용을 6 arm trace 마다 재생해 실험 총지출이 6배로 잡힘 | `benchmark/arms.py` F1-f (shared_s0_cost) |
| Claude Code | 예산 예약이 상계가 아닌데(chars/3 추정) 상한 보장인 것처럼 씀; 커밋 후 초과를 검사하지 않음 | `harmonet/budget.py` F2 (count_tokens, cap_exceeded_post) |
| Claude Code | 호출 예외 시 비용을 $0 으로 확정 | `benchmark/runloop.py` F2 (unknown_cost = 예약액 확정) |
| Claude Code | 분석기가 중복 (task, arm, rep) 을 덮어쓰고 문자열 "True" 를 참으로 해석 | `scripts/gap_analysis.py` F3 |
| Claude Code | BigCodeBench/497 의 C0→D2 판정 뒤집힘(doctest fail/fail → pass/pass)을 "불안정 7건" 에 묶어 원인 없이 기록 — 실제는 예제가 오늘 요일에 의존 | `evidence/week2/pool_probe.md` F5 |

| Claude Code | F4-3 에서 (iii) 를 "X > 27pp" 라는 이유로 제외 — 27 = 바닥 17 + 초과 10 이라 (iii) 가 정답 방향이었음 (G4 정정) | `evidence/week2/gap_power.md` §4 첫머리, `docs/week2_design_draft.md` §4 개정안 v2 |
| Claude Code | F5 개정안이 자명 통과 영역(ρ≥0.9, σ_γ=0 에서 (i)+R1 16~20/20)에 (i) 을 주 통계량으로 배정 | `evidence/week2/gap_floor_g1.json` |
| Fable | F5 지시에서 "결정적이면 교차 적합 = 참값" 이라 했는데 그 참값이 독립 바닥을 포함한다는 것을 놓침. 합성 검증(G1)이 잡아냄 | `evidence/week2/gap_power.md` §4 첫머리 |
| Claude Code | G3: (iii) v2 를 격자 전체에서 돌리고 나서야 검정력 0 을 확인 — 사례 하나로 먼저 바닥 추정치(적합 30.9 vs 참 17.5)를 봤으면 격자 전에 알 수 있었음 | `evidence/week2/gap_floor_g3.md` |

| Fable | 1주차부터 "oracle gap = 상태 조건부 선택의 가치 상한" 을 설계 전제(§0 C3)로 삼음 — 결정적 반복에서는 독립 실현의 차이가 포함돼 상한이 아니라 기술 통계였음. 합성 검증(G1~G3)이 잡아냄 | `docs/week2_design_draft.md` §0 v3, `evidence/week2/gap_power.md` §4 첫머리 |
| Fable | G 지시에서 "바닥 초과분" 통계량(oracle − 고정 − 가산 귀무 기대)을 제안 — 결정적 셀에서 바닥을 추정할 수 없어 검정력 0 (G3). 코덱스의 "여지 ≠ 가치" 가 처음부터 정책 이득을 가리켰음 | `evidence/week2/gap_floor_g3.md`, §4 개정안 v3 |
| Claude Code | (H 에서 새 오류 없음 — G3 의 "oracle − 고정 − 바닥은 구조적 가치를 담지 못한다" 결론 도출이 맞았음) | — |

| Fable | P1(가시 범주 조회표)을 첫 후보 학습기로 둔 것은 합리적이었으나, 가시 검증이 "계속할지"만 갈라 유형을 못 고를 가능성을 사전에 지적하지 못함 — H3 합성에서 무력으로 판명 | `evidence/week2/policy_gain_h3.md` |
| Fable | I2 판정 규칙 R2(CV + 특징 순열)의 귀무 불일치를 못 봄 — 순열 귀무는 "특징 ⟂ 결과" 이고 기각해야 할 귀무는 "정책 이득 ≤ 0" 이다 (난도만 예측해도 특징은 결과를 예측한다). J 에서 진단으로 강등, 판정은 확인 집합 대응 McNemar (2026-09-15, 코덱스 지적) | `evidence/week2/PREREG_pilot.md` v3 §4, `PREREG_pilot_v4.md` §4 |
| Fable | "참 oracle gap 도 상한이 아니다" 과잉 정정 — 참 확률 oracle 이득은 정책 이득의 상한이 맞다. 상한이 아닌 것은 1회 실행 최대의 표본 내 통계. J6 에서 세 양 구분 (코덱스 지적) | `docs/week2_design_draft.md` §0 v3, §4 v4 J6 절 |
| Fable | "12pp 에서 80% 검정력" — 합성 셀 하나(N=150, ρ=0.7, 17/20 [62,97])의 관측 통과율을 검정력 문장으로 과장. J6 철회 (코덱스 지적) | `evidence/week2/policy_gain_h3.md`, `docs/week2_design_draft.md` §4 v3 |
| Fable | 분석기 부트스트랩 누수(복제 행이 CV 학습·평가 양쪽에 들어감)를 I3 dry-run 검토에서 발견 못 함 — 코덱스가 발견, J1 GroupKFold 로 수정. 합성에서 누수본은 N=100 부트스트랩 중심 +1.4pp·CI 17% 좁음 | `scripts/gap_analysis.py` `_group_folds`, `evidence/week2/boot_coverage_j1.md` |
| Claude Code | 비용 누락 — 뒤집힘 부분집합(k=2)과 0회차 비용을 총지출에 넣지 않았고, 출력별 합계를 더하면 재사용 rep1 이 이중 계상됨. J1 원장 검산이 잡음 ($0.2465 vs 원장 $0.2117) | `scripts/pilot_dryrun.py` `spend_report` |
| Claude Code | `_cv_gain` 이 미측정 비용을 `nanmean` 으로 조용히 건너뜀 — cost None 은 합계 None + n_unpriced 여야 함 (J1) | `scripts/gap_analysis.py` |
| Claude Code | 분석기 입력 가드 부재 — infra=True 행, hidden_exposed 미명시 행이 그대로 통계에 들어감 (J1 guard_rows) | `scripts/gap_analysis.py`, `tests/test_policy_gain.py` |
| Claude Code | arms.py arm 별 예산 규칙에 chars/3 추정이 잔존 (F2 에서 원장 예약만 count_tokens 로 바꾸고 max_tokens 규칙은 안 바꿈). J2 에서 count_tokens 경로 재사용 | `benchmark/arms.py` `_max_tokens_for` |
| Claude Code | 재시도 비용 은폐 — `llm._retry_sync` 가 클라이언트 안에서 최대 3회 재호출하는데 원장은 1건만 기록. J2 에서 시도마다 예약·확정 (재시도 2회 후 성공 → 원장 3건) | `benchmark/runloop.py` `budgeted_generate`, `harmonet/llm.py` `generate_once` |
| Claude Code | result.json 재사용 키 누락 — 모델·설정·채점기·특징 추출기 버전이 바뀌어도 옛 결과를 그대로 재사용. s0 해시도 artifact+prompt_context 만 덮음. J2 config_hash·전체 파일 해시 | `benchmark/arms.py` `config_hash`, `_s0_hash` |
| Claude Code | BudgetStop 시 현재 과제의 완료 arm 행이 부분 결과에서 빠짐 (InfraStop 만 partial 처리). J2 | `benchmark/arms.py` `run_task_all_arms`, `benchmark/runloop.py` |
| Fable | J5 실행 게이트를 "설정 파일 해시 일치" 로 정의 — 해시 일치는 승인이 아니다. 승인 기록(검토자·검토 참조·동결 커밋·정책 해시·ID 집합 해시·관문 판정)을 값 단위로 대조해야 한다. K1 APPROVAL.json (2026-09-15, 코덱스 지적) | `scripts/approval.py`, `evidence/week2/APPROVAL.json` |
| Fable | J2 "시도마다 예약·확정" 을 지시하면서 SDK(anthropic) 자체 재시도(max_retries 기본 2)를 인지하지 못함 — runloop 아래에서 원장에 안 보이는 HTTP 호출이 생길 수 있었다. K2 max_retries=0 (코덱스 지적) | `harmonet/llm.py` AnthropicClient |
| Claude Code | J5 게이트가 검증 없이 통과할 수 있었음 — 승인 파일 없이 설정 해시만 맞으면 실제 백엔드 실행 가능, `--stage all` 로 탐색·동결·확인을 한 호출에 돌릴 수 있었음. K1 (코덱스 지적) | `scripts/pilot_dryrun.py` gate_common |
| Claude Code | J2 재시도가 `llm._retry_sync` 만 우회하고 SDK 내부 재시도는 남겨 둠 → HTTP 요청 수 ≠ 원장 건수. K2 모의 429 재현으로 3 == 3 확인 (코덱스 지적) | `tests/test_budget_runloop.py::test_sdk_http_429_twice_then_success_gives_three_ledger_entries` |
| Claude Code | 실패 시도 비용 미귀속 — J2 는 실패 시도를 `commit(projected, projected)` 로 unknown_cost=False 인 채 예약액을 지출로 확정(과금 여부 불명인데 확정, 요금 없음 확실한 429 도 과대 차감). K2 (b)/(c) 분리 (코덱스 지적) | `benchmark/runloop.py` classify_failure |
| Claude Code | s0 가져오기 대상을 탐색 100 전체로 둠 — 프로브에 없는 신규 41 은 가져올 수 없다. K3 source 필드로 59/41 분기 (코덱스 지적) | `benchmark/s0_import.py` prepare, `pilot_explore_ids_bcb.json` sources |
| Claude Code | J4 손실 분해 기준선 불일치 — "베이즈 − truth(π̂−â)" 는 베이즈(참 최선 고정 기준)와 truth(탐색 선택 â 기준)의 기준선이 달라 음수가 나옴(alt_5pp/f=6/seed=8: −3.96pp). K4 두 열로 분리, 코덱스 재계산 +3.29pp 재현 (코덱스 지적) | `scripts/pilot_power_v4.py`, `evidence/week2/pilot_power_v4.md` 검산 |
| Claude Code | J4 시뮬레이션이 "탐색 절차 포함" 이라 하면서 특징 선택·λ 선택·풀 관문을 흉내내지 않음 (f 고정, λ 고정). K4 전체 절차 포함 — 풀 관문이 합성 기저에서 대부분 보류 (코덱스 지적) | `evidence/week2/pilot_power_v4.md` vs `pilot_power_v4_j4.md` |

**패턴 (세 번째, 코덱스 지적으로 발견): "이름을 보고 구현을 읽지 않음."** A1 (validator 이름만 보고 LLM 호출 여부 미확인), A7 (하네스 종료 코드를
통과 신호로 믿음), D2 (`n_run` 이라는 이름을 실행 수로 믿고 공식 채점기가 실행 수를 세지 않는다는 것을 읽지 않음), D5/F1 ("validate 통과" 를
"채점됐다" 로 읽음 — exec_count 0). 다음 인프라 항목부터는 "이 이름의 값이 실제로 무엇을 세는가" 를 테스트로 먼저 고정한다. F 항목들은 전부 코덱스
지적으로 발견됐다 (2026-09-15).

## Week2-A0 LiveCodeBench 로더·stdio 하네스
- 데이터는 HF `livecodebench/code_generation_lite` revision `0fe84c3912ea0c4d4a78037083943e8f0c4dd505` 의 jsonl 을 직접 받는다
  (로딩 스크립트/`trust_remote_code` 불필요). `private_test_cases` 는 base64→zlib→**pickle**(JSON 문자열): 공식 출처 + 고정 revision 파일만
  역직렬화한다. 다른 출처 파일은 넣지 않는다 (`benchmark/lcb.py` docstring).
- stdin 문제는 전부 atcoder, functional 문제는 전부 leetcode. test5+test6(2024-09~2025-04) stdin 217개; **2025-01-01 이후 stdin 은 112개(medium 26)**.
  사전 등록 필터(medium·2025+)로는 프로브 60 도 확인용 ≥200 도 확보 불가 → 프로브 미실행 (pool_probe.md).
- 하네스 메모리 상한은 Windows 에서 미적용(`mem_limit=not_applied(windows)` 로 기록). POSIX 는 RLIMIT_AS 2GiB.
- 비교 규칙은 공식 `grade_stdio` 를 옮김: 줄 수 일치 필수, 줄 단위 strip, 정확 일치 아니면 양쪽 Decimal 리스트 일치. 비수치 줄은 대소문자 구분.
- 원인 불명 1회 관찰: Week2-A0 커밋 직후 콘솔에 `python.exe: can't open file '<repo>\candidate.py'` 가 한 줄 찍힘 (cwd=저장소 루트에서
  `python -I candidate.py` 가 실행된 흔적). 재실행·잔여 프로세스 확인으로 재현 안 됨. 하네스는 후보를 tmp/run 에서만 띄우므로 경로가 설명되지 않는다.
  다시 나타나면 하네스 launch 를 로그로 남겨 추적.

## Week2-B0 MBPP+ 준비·프로브 (2026-09-14)
- **정답 출력 크기 폭발**: Mbpp/255 의 canonical 출력 repr 이 1.29GB(조합 열거), Mbpp/630 이 11MB. JSON 스펙에 못 넣어 두 과제 제외(상한 1MB).
  첫 탐색 스크립트가 이 출력을 eval 로 복원하다 18GB 를 먹어 프로세스를 강제 종료했다. 공식 evalplus 는 이걸 pickle 캐시로 메모리에 들고 있다.
- **plus 입력 0개 과제**: Mbpp/793 은 plus_input 이 비어 있어 plus_only_pass 를 정의할 수 없다 — 풀에서 제외. 정답 전수 확인에서 드러남(375/376).
- **repr 왕복**: 집합의 repr 순서·복소수 `-0-1j` 는 문자열은 달라도 값·타입이 같다. 왕복 검증을 문자열 비교에서 값+타입 비교로 바꿈.
- **공식 채점기는 Windows 에서 안 돈다**: `time_limit` 이 SIGALRM, `reliability_guard` 가 resource 모듈. 동등성 오라클은 이 둘을 비활성으로
  두므로 우리가 말할 수 있는 건 "비교 판정이 검사한 17개 사례에서 공식과 일치" 까지다. 시간 제한·격리 동등성은 주장하지 않는다 (B2 1-2 정정).
- **atol 상태 전이**: 공식 루프에서 `atol` 이 케이스 사이에 바뀐다(float 기대값 이후 1e-6 유지). 순서를 바꾸면 판정이 달라지는 케이스를
  테스트로 고정(`atol_state_*`). 스펙 생성 시 케이스별 atol 을 미리 계산.
- **가격표 별칭 불일치**: API 응답 `model` 이 `claude-haiku-4-5-20251001` 이라 `claude-haiku-4-5` 항목과 안 맞아 프로브가 cost_usd=None 으로 돌았다
  (경고는 찍혔음). 날짜 접미사를 떼서 조회하도록 수정(90498eb). HumanEval 프로브 때는 토큰으로 손계산했었다.
- **프로브 결과 85%** → [30,70] 밖 → unconfirmed. `evidence/week2/pool_probe.md` 프로브 3.

## Week2-B2 / C0 (2026-09-14)
- **파이프 교착**: 과제별 워커가 결과 JSON(최대 ~800KB)을 stdout 으로 내보내자 64KB 파이프가 차서 자식이 막히고 부모는 종료를 기다리다 30s 에 kill —
  전 과제가 "시간 초과" 로 제외될 뻔했다. 결과·stderr 를 파일로 바꿔 해결. Windows venv 의 python.exe 는 런처라 실제 인터프리터가 자식 프로세스 →
  RSS 감시·kill 은 psutil 트리 단위로.
- **Mbpp/255** 는 이제 메모리 상한(2.49GB > 2GiB)으로 제외된다 — 이전 "repr 1.29GB" 와 같은 과제, 사유만 바뀜. 스펙 재생성 후 프로브·확인 ID 불변.
- **BCB 공식 이미지**는 ENTRYPOINT 가 `bigcodebench.evaluate` 라 `--entrypoint python3` 로 덮어야 우리 하네스가 돈다. 15.1GB.
- **BCB doctest 는 절반 이상이 예시용**(가상 경로·파일): 정적 스크린 통과 637 중 canonical 로 실제 통과하는 건 412. 정적 스크린은 "seed/random/Axes" 로
  384개를 걸렀는데, 그중엔 `isinstance(result, float)` 처럼 결정적인 예제도 있었을 것 — 보수적으로 잃은 셈.
- **B 상한 조건**: 사전 등록의 B ≤ 70% 를 sonnet-4-6 이 75% 로 넘겼다. A 는 창 안. 규칙대로 unconfirmed, 재검토 초안(`docs/week2_review_draft.md`)만.

## Week2-D (2026-09-14) 예상과 달랐던 것
- **k=3 교차 적합 gap 은 참 상호작용을 거의 다 깎아 잰다** (`evidence/week2/power_prelim.md` §2): 합성에서 참 상호작용 0.3(oracle gap 17pp)이어도
  교차 적합 추정 대상은 ≈ 0. 6 arm 중 과제별 최선을 반복 2개로 고르는 선택이 잡음이라 최선 고정(전 과제 합산)에 진다. 10pp 문턱을 이 통계량에
  걸면 참 상호작용 ≈ 0.5 이상이어야 통과. 설계 §4-3 경고의 실제 크기. 판단 대상(문턱을 거는 추정량·k·후보 arm 수).
- 합성 검증 (b) 는 "oracle gap 포함" 으로 두면 0/5 였고, 추정 대상을 교차 적합 통계량의 기대값(몬테카를로)으로 정의해야 20/20 이 된다 — 부트스트랩이
  덮는 것은 그 기대값이지 oracle 이 아니다.
- 이미지 안 Python 3.10: 스레드에서 fork 한 자식은 정상 종료해도 exitcode 1. `reliability_guard` 아래서는 자식이 죽어도 join(timeout) 이 안 깨어난다
  (손자가 sentinel 보유). 공식 채점기는 둘 다 안 보므로 드러나지 않던 문제.
- Windows: docker CLI 프로세스를 죽여도 파이프가 안 닫혀 컨테이너가 끝날 때까지 대기 — 타임아웃 처리는 `docker kill <name>`.
- 정적 필터 v1 의 `open\(\b` 는 아무것도 못 잡는 패턴이었다(괄호 뒤 `\b`). 테스트 없이 정규식을 믿은 것.
- D2 기대 테스트 수 계수: test 모듈 3개(227·594·721)는 후보 없이 로드되지 않는다(클래스 정의 시점에 task_func 참조). 실행 수를 검증할 수
  없으므로 채점 불가로 제외 — 공식 채점기라면 통과시켰을 과제.
- atexit 은 multiprocessing 자식(os._exit 종료)에서 실행되지 않아 "정답 뒤 atexit os._exit" 은 공격 경로가 아니었다 — 테스트에서 제외.

## Week2-F1 정정 (2026-09-15)
- D5 보고의 "mock 스모크 3 과제 × 6 arm: 18 traces validate … eval:hidden 0" 은 맞지만, **채점은 한 건도 컨테이너에서 돌지 않았다**: MockLLM 이 코드가 아닌
  문장을 내서 18/18 이 정적 `error`(AST 단계, exec_count 0)였다. "18행 공식 이미지에서 돌았다" 는 D3 문서 문장은 틀렸고 정정했다.
  F1 에서 유효 코드 시나리오 mock(정답/오답/근접오답)으로 3 과제 × 6 arm × k=2 = 36 행을 실제 Docker 에서 돌려 기대 히든 결과와 36/36 일치.

## Week2-G (2026-09-15) 예상과 달랐던 것
- (i)+R1 은 σ_γ=0 에서도 ρ≥0.9 면 통과한다(G1). "교차 적합 = 참값" 의 참값이 독립 바닥을 포함했다.
- (iii) v2 는 크기·편향은 맞지만(G2) 검정력이 0 이다(G3): 결정적 셀에 가산 로짓을 적합하면 p̂ 가 수축해 바닥이 관측만큼 부푼다.
- E1 의 γ_ia(셀별 i.i.d. 지속 효과)는 ρ=1 에서 실현 운과 구별 불가 — 생성기의 "초과분" 이 학습 가능한 구조가 아니었다. 유형 수준 구조로 바꿔도 oracle 이 천장이라 안 움직인다.
- 워커 풀 × BLAS 스레드 과다로 156×156 solve 가 2.5s — OMP/OPENBLAS 스레드 1 로 고정해 0.14s/분석.
- δ_z=2(s0 조건부 구조)는 가산 적합의 과제 효과가 흡수한다 — σ_γ=0 에서 초과분 ≈ 0 이 δ_z 유무와 무관하게 성립해 G2 검증을 E1 그대로 할 수 있었다.

## Week2-H (2026-09-15) 예상과 달랐던 것
- 가시 범주 조회표(P1)는 무력하다: 가시 검증 결과는 s0 성공 여부(z)만 알려주고 "어느 계속 arm 이 이 과제에 맞는가"(유형)는 못 알려준다. 정책 이득은 error_kind·산출물 길이 같은
  유형 특징을 쓰는 P2 에서만 나온다 — 실제 데이터의 §8 신호 중 어느 것이 유형을 담는지가 3주차의 핵심 변수.
- s 축만으로는 참 정책 이득이 6.5pp 까지라 10pp 문턱 위를 볼 수 없었다 → Δ(유형 효과) 축을 추가해야 했다. 생성기의 '신호 강도' 와 '효과 크기' 는 다른 축이다.
- P2 는 s=0 에서 −2~−4pp 편향(과적합의 CV 비용)이라 |편향| ≤ 2pp 기준을 못 맞춘다. 음수라 통과 방향엔 보수적이지만 참 이득이 작을 때 점추정을 깎는다(N=100 에서 −3~−4pp).
- 정책이 고른 arm 은 최선 고정(대개 B-expert)보다 싸다 — 예산 매칭 조건에서 정책 쪽이 불리하지 않았다.
- 검정력 격자 1,920 분석에 52분: P2 의 특징 순열 500 × CV 25 회 적합이 지배. 실제 분석기 기본값(순열 2000·R=20)은 한 데이터에 수 분.

## Week2-I (2026-09-15) 기록
- **N 곡선 우상향 확인 — 통계량 v3 채택 근거.** 정책 이득(P2)의 검출(p<0.05)은 N 100→300 에서 9→15→18→19/20 로 오르고(참 6pp), 참 12pp 에서는 20/20.
  이전 통계량(교차 적합 oracle gap, F4)은 N 60→200 에서 X 가 거의 안 줄었다(선택 잡음 지배). 정책 이득은 N 에 민감해야 정상이고 실제로 그렇다 — v3 를 채택하는 근거.
- **P1 무력의 의미.** 가시 검증 결과는 "s0 를 이대로 낼지, 더 할지"(종료 여부)를 갈라 주지만 "어느 계속 arm 인가"(유형)는 담지 않는다. 유형은 오류 클래스·산출물 길이·
  라이브러리 같은 다른 신호에 있다. 따라서 파일럿의 주 분석은 P2-post 이고, P2-post − P2-pre 가 "실행 후 신호의 추가 가치" 를 잰다.
- I3 dry-run: 시나리오 mock → arms(k=1, 6 arm + 뒤집힘 부분집합) → 특징 → P2-post/P2-pre/P1(순열 2000·부트스트랩 1000) → 판정, 437s. 실제 파일럿과 백엔드 환경변수만 다르다.
- 예상과 달랐던 것: (1) numpy 기본 BLAS 스레드로는 CV 1회 1.7s, 스레드 1 로 0.09s — 워커 14개까지 겹치면 수십 배 느려져 첫 dry-run 이 3시간 코스였다.
  gap_analysis 모듈 import 시 스레드 1 로 고정. (2) 6 과제 dry-run 의 판정은 당연히 미확인(CI [-15, 81]pp) — 형식 점검용이며 수치는 의미 없음.

## Week2-J (2026-09-15) 예상과 달랐던 것
- **v4 구조의 검정력은 낮다.** 학습 100 / 평가 200, P2 λ=1.0: 참 베이즈 이득 10pp 에서 관측 통과율 3/20 (f=6) — 검출(p<.05)은 17/20 이지만 학습된 정책의 참 이득이
  7.5pp 라 "평균 d ≥ 10pp" 문턱에 걸린다. 15pp 에서 15/20 (f=6), 9/20 (f=12), 3/20 (f=20). 잡음 특징 15 열이 N_e=100 학습을 빠르게 망가뜨린다(베이즈 대비 손실 2.6 → 8.5pp).
  귀무 2종은 0/60 [0,6]. 추정은 무편향(±1pp, 무학습 평가) — 문제는 편향이 아니라 100 과제로 배운 정책의 질이다. 해석: 확인 판정의 "통과" 는 참 이득이 충분히 크고
  특징이 적을 때만 기대할 수 있고, 미확인은 "이득이 작다" 와 "탐색 100 이 부족했다" 를 구별하지 못한다 — PREREG v4 결론 문장에 그대로 반영.
- **원장 검산이 첫 실행에서 바로 잡아낸 이중 계상.** 뒤집힘 실행은 주 실행의 rep1 result.json 을 재사용하므로 출력별 합계를 더하면 6 행이 두 번 들어간다.
  "총지출을 계산하지 않고 원장에서 읽는다" 는 규칙이 없었다면 $0.035 과대 보고를 못 봤을 것.
- **부트스트랩 누수의 크기.** 수정 전후 CI 포함률은 20회 기준으로 구별되지 않지만(19/20 vs 20/20), 복제 분포의 중심이 +1.4pp 이동하고 CI 가 17% 좁아진다 — "포함률이 괜찮다" 로는
  누수를 못 잡는다. N=200 에서는 차이가 거의 사라진다(+0.1pp).
- v4 파일럿 dry-run(탐색 4 / 확인 2, mock, 실제 Docker 채점): 두 단계 391s + 117s, 총지출 원장 $0.2088 = 탐색 $0.1537 + 확인 $0.0551, 검산 일치. 판정 미확인(N=2, b=1 c=0 p=0.5) — 배관 점검용.
- 15pp 참 이득은 v3 생성기 기저(BETA)에서 도달 불가(천장 ≈ 14pp) — 기저를 평탄화한 변형에서 Δ 를 맞췄다. "효과 크기 축" 이 생성기 구조에 묶여 있다는 것을 다시 확인.

## Week2-K (2026-09-15) 기록·예상과 달랐던 것
- **실행 순서 고정** (`PREREG_pilot_v4.md` §0): K 완료 → 코덱스 재검토 → `APPROVAL.json`(stage=explore, 탐색 실행 승인) → 탐색 100 실행 → 동결 커밋 → `APPROVAL.json` 갱신
  (stage=confirm, freeze_commit·policy_hash 기입 = 확인 실행 승인) → 확인 200 실행 → 분석 1회. 실제 백엔드에서 `--stage all` 은 코드가 거부한다.
- **풀 관문이 합성에서 대부분 '보류'.** 생성기 v3 의 B-expert 기저(BETA 0.8, u~N(0,1))가 최고 arm 성공률 ≈ 80% 를 만들어 K4 복제의 55~95% 가 관문에 걸린다.
  실제 풀(프로브 B-solo 75%)에 대한 진술이 아니다. *(L6 정정: K4 표의 '관문 무시' 25/34 는 "관문을 제거한 절차의 통과율"(b)이지 "관문 통과 후 조건부 결과"가 아니다 —
  후자는 (c) 10/14. 세 양은 `pilot_power_v4.md` 에 별도 열. 또 K4 표는 현행 사전 등록 절차(겹 안 선택, K5×R20)와 다른 절차(전체 자료 선택 → CV R=5)의 결과라 `_k4` 로 보존.)*
- **λ 선택은 거의 항상 0.3.** 메뉴 {0.3, 1, 3} 에서 CV 는 f 와 무관하게 0.3 을 고른다(alt_10pp 19/20) — 정책 이득 CV 는 약한 정규화를 선호한다. 특징 수는 이 결과로 줄이지 않는다(K5).
- **max_selected 20 은 f=20 부터 작동**: 범주 열(visible 2 + error_kind 3 = 5 one-hot)이 상한에 들어가 선택 열 수 17 로 잘린다. 실제 메뉴 28(pre 17 + post 11) 에서는 post 의 범주 2열이
  visible·error_class 로 최대 2+9 one-hot 을 차지할 수 있어 수치 열이 ≤ 9 개까지 줄 수 있다 — 탐색에서 확인할 것 (사전 등록 규칙은 그대로).
- 코덱스 재계산값 +3.29pp 는 J4 정책(λ=1 고정)에서 정확히 재현됐고, K4 절차(λ*=0.3)에서는 +3.54pp — 같은 seed 라도 절차가 다르면 손실이 다르다.
- s0 준비 dry-run(실제 ID 파일 100, 가져오기 59 + mock 생성 41, 실제 docker 가시 검증 100회): 7분 15초, 실패 0. 가져오기의 원본 대조 10항목 전부 통과.

## Week2-L (2026-09-15) 기록·예상과 달랐던 것 — 코덱스 K 검토 반영
- **L1**: arm 별 예산이 첫 시도에만 적용되던 것을 시도마다로. 코덱스 재현(잔여 $0.00512, timeout → 성공, 귀속 $0.00972, status ok)은 수정 후 "timeout → 잔여 0 → 추가 호출 0, 귀속 $0.00512,
  refused_after_attempts" 가 된다. 실측(measured_usd)과 보수적 예약 귀속(unknown_reserved_usd)을 행·요약·보고서에서 분리 — 귀속액은 청구액이 아니다.
- **L5**: 성공 없이 끝난 시도(예약 거부·재시도 소진·치명적 HTTP·불명 2회)도 `incomplete_*.json` 에피소드로 남기고 원장과 대조. 이전에는 BudgetStop 에 시도 정보가 없어 원장에만 비용이 남았다.
  s0 생성 중 중단도 같은 방식. 미완료 기록은 `guard_rows` 가 분석 입력에서 거부한다.
- **L2**: 승인 대조 = 승인 문서 값 + 동결 파일 내부 + 관문 수치 일관성 + freeze_commit blob + 검증 범위 파일 25개 해시. 이전(K1)은 "존재하는 조상 커밋" 과 파일 해시만 봤다.
- **L3 — 통합 전 불일치 재현**: alt_5pp/f=28/seed=8 에서 K4 절차(전체 자료 선택 → CV R=5) λ=0.3, 현행 절차(겹 안 선택, K5×R20) λ=1.0, N=5000 예측 불일치 **13.82%** (코덱스 값 그대로).
  통합 후 실행기·시뮬레이터 경로는 λ·부분집합·계수·예측이 비트 단위로 같다(입력 경로까지 rows → policy_tensor 로 맞춰야 계수가 같았다 — 행 순서가 다르면 1e-14 차이).
- **L3 재실행 결과 vs K4** *(M5 정정 — 원시 720행에서 직접 확인)*: 조건별 (a) 전체 절차 통과 수 20 셀 전부 동일, 복제 720 중 λ 선택 변경 **248**, (a) 통과 여부 변경 **0/720**
  ((b) 관문 제거 통과 여부 변경 1/720). 참 이득 변화는 **조건별 평균으로 최대 0.23pp, 개별 복제로는 최대 2.36pp** — 이전 문구 "≤0.2pp" 는 조건 평균에만 해당하고 개별 복제에는
  틀린 표현이었다. 절차 차이가 λ 와 개별 정책을 바꾸지만 이 생성기에서는 판정 결과가 움직이지 않았다 — "차이가 없다" 가 아니라 "이 합성에서 판정에 영향이 작았다". 소요 413s (R=20, 12 워커).
- **L6 세 양**: [10,15)pp 구간 (a) 10/33, (b) 25/33, (c) 10/13 (재실행; K4 는 10/34, 25/34, 10/14). 합산 구간 행은 f 마다 같은 seed 기저를 재사용하므로 독립 시행이 아니다 → 건수·비율만.
- **L4**: post 정책이 B-solo 를 골라도 s0 는 이미 지불 — 배포 비용에 포함. dry-run(확인 N=2)은 정책이 A-role·B-expert 를 골라 수치 변화 없음(정책 배포 $0.0087 = arm $0.0058 + s0 $0.0029);
  단위 테스트로 규칙 고정(s0 $0.003 + B-solo $0.005 → 정책 $0.008, 고정 B-solo $0.005).
- 첫 재실행 보고서에서 "arm 실측 $0.1479 > arm $0.1247" — 실측/귀속 합이 뒤집힘 실행의 재사용 rep1 행을 이중 계상하고 있었다(own 은 셀 중복 제거, 실측은 아님). 셀 단위로 통일.
- 남은 한계: 합성 생성기의 최고 arm 성공률(≈80%)이 관문 근처라 관문 보류가 많다(생성기 성질); (c) 는 관문 통과 복제가 적어(alt_10pp 1/20) 구간이 넓다; 검정력 자체는 여전히 낮다
  — *(M5 정정)* "참 10pp 에서 (b) 3/20" 은 **생성 조건 alt_10pp(베이즈 목표 9.8pp)** 의 결과이며, 그 조건에서 f=6 로 **학습된 정책의 평균 참 이득은 약 8.0pp** 다. "정책의 참 이득이
  10pp 일 때 검정력 15%" 로 읽으면 안 된다; 참 이득 구간별 표([10,15)pp (b) 25/33)가 그 질문에 가깝다(단, 합산 행은 독립 시행이 아님). alt_15pp/f=6 (b) 16/20. 학습 규모·특징 수·풀·문턱은
  바꾸지 않는다(사전 등록 유지, 코덱스 재검토 대상).

## Week2-M (2026-09-15) 기록·예상과 달랐던 것 — 코덱스 L 검토 잔여 수정
- **보고 문구 정정 (M5)**: (1) 위 L 절의 "참 이득 변화 ≤0.2pp" → 조건 평균 최대 0.23pp / 개별 복제 최대 2.36pp 로 구분. (2) "참 10pp 에서 통과 3/20" → 생성 조건 alt_10pp 의 결과,
  학습 정책 평균 참 이득 ≈8.0pp. (3) L 보고의 dry-run "실측 $0.1740 / 불명 귀속 $0" 은 **arm 부분의 실측**이었다: arm $0.1740 + s0 $0.0174 + 0회차 $0.0174 = 총 $0.2088 (원장).
  코드의 비용 누락이 아니라 보고 범위(어느 부분의 실측인지)를 적지 않은 문제. 보고서 `cost` 항목명을 `arms_measured_usd` 로 두어 범위를 고정했다.
- **M1 재현**: 실제 CLI 경로에서 1차 timeout→400(귀속 $0.00622, 원장 정지 안 됨) → 패치 전 재개는 새 arm 예산으로 성공 호출 $0.00450, 누적 $0.01072 > 상한 $0.010 (코덱스 값 그대로).
  패치 후 재개 호출 0, 원장 불변, `stopped_reason=unresolved_incomplete_arm`. 잔여 예산·중간 산출물 복원은 만들지 않았다(fail-closed, 수동 판단).
- **M2 재현**: `s0_import.prepare(source=new)` 에서 timeout×2 → CallAborted(원장 $0.04184, 기록 0건), timeout→400 → BudgetStop(원장 $0.02092, 기록 0건). 패치 후 공통 경계
  `make_s0_guarded` 가 s0/incomplete_*.json(task/source/설정 식별자·시도·실측/귀속·사유)을 남기고, 재실행은 미해결 실패를 자동 재생성하지 않는다.
- **M3 재현**: 예약 $0.02, 실측 $0.02628, cap $0.025 → cap_exceeded_post 에서 예외 usd 0 (원장 $0.02628). 패치 후 usd = 실측 + 불명 귀속 = $0.02628, 예외·미완료 기록·보고서가
  같은 집계(`_attempt_totals`). None(실측 미상)은 0 으로 바꾸지 않는다.
- **M4**: 부모 환경변수(HARMONET_BCB_IMAGE 등)가 설정과 다르면 자식 환경으로 조용히 흘러가던 경로를 거부로 바꿨다(덮어쓰기 아님). 코드 기본값과 설정의 일치도 검사.
- 예상과 달랐던 것: `dict(os.environ, **extra, **g)` 가 mock 에서 모델 키 중복으로 TypeError — 테스트가 anthropic 경로만 덮고 있었다(mock 무충돌 케이스 추가).
  M1 fail-closed 가 L5 의 "재개 시 에피소드 2건" 테스트와 충돌 — 재개 자체가 거부되므로 에피소드 1건·원장 불변으로 갱신.
