# G1 재실행 (2026-09-12) — AUDIT.md N1·N2 수정 후

조건: Ollama `qwen2.5-coder:7b`, HumanEval 20 + MBPP 20 과제 × 3반복 = 120행, `G1_DISABLE_EVAL_REPAIR=1`(norepair), 토큰 전부 API `measured`.

## 수정 사항

- **N1**: `huggingface-hub` 1.4.1 → 1.31.0 (requirements에 `>=1.5.0,<2.0` 고정). `embed.py` 폴백을 fail-closed로 변경, 러너 시작 시 `assert_embedding_sane()` 게이트 추가.
- **N2**: `external_g1.py::_infer_entry_point_from_tests`를 참조 코드의 def + 테스트 호출 기반으로 교체. 구 정규식은 MBPP 427개 중 19개에서 오답(`set` 5, 무매치 14); 실험 범위 첫 20개 중 mbpp_2·mbpp_7. 새 추론은 427개 전부 일치.

## 결과

| 시스템 | 정확도 | 과제단위 95% CI (n=40, bootstrap) | 평균 토큰 | prompt / completion | 비고 |
|---|---:|---|---:|---|---|
| single | 95.0% | 87.5 – 100 | 244.9 | 161 / 84 | |
| harmonet_v2 (진입점 수정) | 95.8% | 89.2 – 100 | 254.6 | 158 / 96 | 120행 전부 calls=1, repair 발동 0 |
| harmonet v1 (임베딩 복구) | 95.0% | 87.5 – 100 | 433.8 | 284 / 150 | 120행 전부 seeds_received=2, tasks_completed=2; repair_used 3/120 |

구 실행(9월, 버그 상태): v2 92.5% / 274.3 tok (calls=2 6행 = mbpp_2×3, mbpp_7×3), v1 seeds_received=0 ×120.

## 짝 비교 (40과제, 3회 통과 수)

| 비교 | 승 / 무 / 패 | 차이 과제 |
|---|---|---|
| v2 vs single (신) | **1 / 39 / 0** | mbpp_20: v2 1/3, single 0/3 |
| v1 vs single (신) | **0 / 40 / 0** | — |
| v2 vs single (구) | 0 / 38 / 2 | mbpp_2, mbpp_7 (하네스 버그) |

mbpp_2·mbpp_7은 수정 후 v2 3/3 통과. 구 "2패"는 전부 진입점 버그의 산물. 실패 과제는 HumanEval/10(전 시스템 0/3), mbpp_20(single 0/3, v2 1/3)뿐.

## 해석

- v2 = single. 정확도·토큰 모두 CI 안이고 짝 비교 차이 1건은 mbpp_20 한 번 통과로 노이즈 수준. "같거나 나쁨" 서술은 철회, "구별되지 않음"으로.
- v1은 공명 게이트가 실제로 열린 상태에서 single과 정확도 동일, 토큰 1.8배(builder+validator 두 씨앗 실행). 이것이 9월 실행에서 측정되지 않았던 "기제가 살아 있는" v1의 첫 수치다. 단, validator는 builder 출력을 읽지 않으므로(agent.py:155, :759-772) 두 번째 호출은 실제 검증이 아니다.

## 파일

- `g1_fair_v1_norepair_20x3.*` — v1, 임베딩 복구
- `g1_fair_v2_norepair_fixedep_20x3.*` — v2, 진입점 수정
- `g1_fair_single_norepair_fixedep_20x3.*` — single, 진입점 수정
- `v1_mock_smoke.*` — mock 스모크(seeds_received=2 확인용)
