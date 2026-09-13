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
