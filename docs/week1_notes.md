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
  기대 출력 생성용 canonical 실행 1회. **채택은 승인 후.**
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
