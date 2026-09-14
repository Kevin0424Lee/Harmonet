# RESCORE_bcb — 프로브 4 후보 120개를 D2 채점기로 재채점 (2026-09-14)

채점기: `harmonet/bcb_check.py` v harmonet-bcb-check-d2.1 (실행 수 검사 testsRun == expected ∧ skipped == 0 ∧ 정상 종료 + unittest 참조 사전 바인딩). 공식 이미지 동일.
원 프로브 결과(`pool_probe_bcb_{A,B}.json`, 사전 등록 판정)는 수정하지 않는다.

- 재채점 행: 120 (A 60 / B 60), 소요 453s, infra=True 행: 0
- **뒤집힌 행: 0**
- A: 원 pass 38/60 → 재채점 pass 38/60
- B: 원 pass 45/60 → 재채점 pass 45/60
- 뒤집힌 행 없음: 120 후보 중 unittest 를 패치하거나 실행 수를 줄인 후보가 없었다는 뜻이며, 검사가 필요 없었다는 뜻은 아니다.
