# 재채점 대조 (A7c) — 7B norepair 20×3, 2026-09-13

## 1. 같은 후보를 두 채점기로 (표본 노이즈 없음)

| system | n | 구 채점기(종료 코드) 통과 | 새 채점기(score_hidden) 통과 | 거짓 통과(구=통과·신=불통과) | 역전(구=불통과·신=통과) |
|---|---|---|---|---|---|
| harmonet | 120 | 112 (93.3%) | 112 (93.3%) | **0** (0.0%) | 0 |
| single | 120 | 114 (95.0%) | 114 (95.0%) | **0** (0.0%) | 0 |
| harmonet_v2 | 120 | 114 (95.0%) | 114 (95.0%) | **0** (0.0%) | 0 |

### 뒤집힌 행 (거짓 통과)

(없음)

## 2. 구 CSV(후보 미저장, 별도 실행) 와 과제별 통과 수 대조 — 표본 노이즈 포함, 참고용

- **single**: 구 통과 114/120 → 신 통과 114/120; 과제별 통과 수가 다른 과제 0/40: 
- **harmonet_v2**: 구 통과 115/120 → 신 통과 114/120; 과제별 통과 수가 다른 과제 1/40: mbpp_20(1→0)
- **harmonet**: 구 통과 114/120 → 신 통과 112/120; 과제별 통과 수가 다른 과제 2/40: HumanEval/8(3→2), mbpp_61(3→2)

## 3. 추출 방식 분포 (extraction) 와 outcome 분포

- harmonet: extraction {'heuristic': 120} | outcome {'pass': 112, 'fail': 8}
- single: extraction {'fenced': 120} | outcome {'pass': 114, 'fail': 6}
- harmonet_v2: extraction {'fenced': 120} | outcome {'pass': 114, 'fail': 6}

MBPP 행은 `hidden_exposed=True` (채점 test_list 가 프롬프트에 공개) — 히든 점수가 아니다. HumanEval 행만 히든 채점.
