# Week 1 진행 메모 — Part C 설계에 반영할 항목

Part A 진행 중 확정된 사실과, 2주차 설계(`docs/week2_design_draft.md`)에 넣어야 할 항목의 누적 목록.

## Part C "실행 환경" 항목
- `evidence/*/run_*.ps1` 등 기존 실행 스크립트는 A2 이후 `HARMONET_ALLOW_NO_REDIS=1` 없이는 즉시 `RuntimeError`.
  재실행 시 반드시 추가. Mock 은 `HARMONET_LLM_BACKEND=mock` 명시 필요 (자동 폴백 없음).
- legacy 메커니즘(Kuramoto·TDA·SOC)은 `HARMONET_LEGACY_MECHANISMS=1` 일 때만. 기본 실행은 코사인 + 적응형 δ 게이트.

## Part C 공정성 항목
- `benchmark/agents_harmonet_v2.py:repair_after_eval` 는 외부 채점기의 실패 출력(`eval_error`, 히든 테스트 결과)을
  프롬프트에 넣는다 — N3 와 같은 누출 패턴. 2주차 설계에서 "운영 중 검증 신호"로 쓰지 말 것 (`G1_DISABLE_EVAL_REPAIR=1`).
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
