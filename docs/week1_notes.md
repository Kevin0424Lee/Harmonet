# Week 1 진행 메모 — Part C 설계에 반영할 항목

Part A 진행 중 확정된 사실과, 2주차 설계(`docs/week2_design_draft.md`)에 넣어야 할 항목의 누적 목록.

## Part C "실행 환경" 항목
- `evidence/*/run_*.ps1` 등 기존 실행 스크립트는 A2 이후 `HARMONET_ALLOW_NO_REDIS=1` 없이는 즉시 `RuntimeError`.
  재실행 시 반드시 추가. Mock 은 `HARMONET_LLM_BACKEND=mock` 명시 필요 (자동 폴백 없음).
- legacy 메커니즘(Kuramoto·TDA·SOC)은 `HARMONET_LEGACY_MECHANISMS=1` 일 때만. 기본 실행은 코사인 + 적응형 δ 게이트.

## Part C 공정성 항목
- v1 어댑터의 키워드 기반 repair 경로(`benchmark/agents_harmonet.py`, `HARMONET_REPAIR_KEYWORD_THRESHOLD`)는
  HarmoNet 에만 있는 2차 LLM 호출. 조건 간 비교 시 끄거나 전 조건에 동일 적용.

## Part C 전제 조건 (2주차 첫 작업)
- validator 가 실행할 **공개** 테스트: HumanEval docstring 의 `>>>` 예제를 doctest 로 추출해 `task_spec["tests"]` 에 넣는다.
  현재 G1 러너는 채점용 히든 테스트를 넣지 않으므로(누출 방지) validator 는 AST + 진입점 검사까지만 수행.

## A1~A3 관찰 기록
- Architect 비공명: A0 의 mock 실행 1회에서 architect 가 builder 피드백 씨앗을 실행하는 것을 관찰(2회 중 1회, 비결정적).
  A1 에서 `target_role` 로 구조적으로 차단. A3 에서 Kuramoto 를 legacy 로 옮긴 뒤 mock 3회 × (legacy on/off) 모두
  에이전트별 호출 수·공명 이벤트 수 동일 → **Kuramoto 위상은 원천이 아님**. `target_role` 필터를 끄고 5회 돌려도
  architect 실행 0 으로 A0 관찰은 재현되지 않음. 남은 후보: async 스캔이 builder 의 씨앗 투하 전/후 어느 시점에
  도는지(틱 내 순서) + `priority_delay` sleep 기반 claim 경쟁. 주 경로의 마지막 난수 원천(감지기 초기 위상,
  `resonance.py:71`)은 legacy 가 아닐 때 0 으로 고정.
- validator 결과 씨앗의 `verification` 은 `_scatter_feedback_seed` 가 `task_results.append` 전에 호출돼
  한 결과 전 것을 가리킬 수 있음 → A4 에서 판정을 인자로 직접 전달.
