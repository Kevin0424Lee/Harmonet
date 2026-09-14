# 파일럿 사전 등록 — **v3 (미승인, 이력)** · Week2-I2, 2026-09-15 · 실행 없음

**이 문서는 실행되지 않았고 승인되지 않았다. 현행 초안은 `PREREG_pilot_v4.md`(J3, 2단계 동결). v3 를 이력으로 보존한다 — CV+특징 순열 R2 는 코덱스가 판정 규칙으로 승인하지 않았다(귀무 "특징 ⟂ 결과" ≠ "정책 이득 ≤ 0"), 진단으로 강등.**

**상태(v3 당시): 실행 없음. 승인 대기 2건 — (a) B 상한(교수님 문서 5절 질문 2), (b) 설계 개정안 v3(코덱스).** 둘이 오기 전에는 유료 호출 0.

| 실행 전 기입란 | 값 |
|---|---|
| 풀 | **[ ] BCB   [ ] 보류** — B 상한 판단 결과에 따라 실행 전 기입. BCB 이면 아래 그대로, 보류이면 이 문서는 실행하지 않는다 |
| B 상한 판단 | (미기입) |
| 개정안 v3 검토 | (미기입) |

## 1. 풀·집합 (ID 파일 동결, seed 20260915, `benchmark/pilot_split.py`)
- 적격 풀: BCB Complete 적격 **403** (`bcb_eligibility.json`, F5: 3회 실행 전부 pass ∧ 이력 일치, 개발용 6 제외).
- **탐색 집합 59** = 프로브 60 중 재적격 통과분 (`pilot_explore_ids_bcb.json`; 565 는 필터 v2 로 제외). s0 = **프로브의 A-solo 산출물 재사용**:
  같은 모델(claude-haiku-4-5-20251001)·프롬프트(complete_prompt)·temp 0.2·max_tokens 4096·시스템 프롬프트로 생성됐고, D2 채점기 재채점에서 뒤집힘 0
  (`RESCORE_bcb.md`), 산출물·비용·토큰이 `pool_probe_bcb_A.json` 에 있어 s0 스냅샷을 그대로 만들 수 있다 (`benchmark/s0_import.py`: 가시 검증만 다시
  돌려 verify_visible.json·decision_signals.json 을 채움, LLM 호출 0). 재사용은 s0 생성비 $0.18 절약이 아니라 **프로브와 파일럿의 s0 를 같게 두기 위한 것**.
- **확인 집합 200** = 미사용 344(적격 403 − 프로브 60 전부)에서 seed 추출 (`pilot_confirm_ids_bcb.json`). 예비 144 (`pilot_reserve_ids_bcb.json`).
  확인 집합의 생성·채점 결과는 분석 1회 전까지 열람 금지.
- 뒤집힘 부분집합 = 탐색 집합에서 seed 30개 (`flip_subset_ids`): A-self·B-expert 만 k=2 → ρ̂ 보고용, 통계량에는 쓰지 않는다.

## 2. 실행
- arm 6개 (T / A-self / A-self×k / A-role / B-expert / B-solo), **k=1**, A = claude-haiku-4-5, B = claude-sonnet-4-6, temp 0.2, max_tokens 4096.
- 예산 규칙 §3: b_cont = 탐색 0회차의 B-expert 1회 비용 중앙값 → 이후 모든 계속 arm 의 max_tokens 규칙·거부율 기록 → 확인 집합에 같은 b_cont 적용.
- 채점: 공식 BCB 이미지(digest 고정), 가시 = doctest TestCases, 히든 = 공식 test, D2 채점기 d2.1, post_hoc 만.
- 원장: `HARMONET_BUDGET_CAP=14` (탐색 $4 + 확인 $10), count_tokens 예약, 커밋 후 초과·미측정·인프라 장애 시 즉시 중단 (F2, D1).
- **순서**: (1) 탐색 59 실행 → 파이프라인·λ·특징 점검은 **여기서만** 허용 → (2) 모든 설정(λ, 특징 집합, b_cont, seed)을 동결 커밋 → (3) 확인 200 실행 →
  (4) 분석 1회 → 보고. 확인 결과를 보고 설정을 바꾸지 않는다.
- 명령 (백엔드 환경변수만 dry-run 과 다름): `scripts/pilot_dryrun.py` 의 실제 모드 = `HARMONET_LLM_BACKEND=anthropic HARMONET_BUDGET_CAP=14 …`.

## 3. 특징·학습기 (I1, 고정)
- pre: prompt_chars, n_examples, lib_*(상위 12 + other), n_args, mentions_return. post: visible, n_failed, error_class(상위 8 + other/none), artifact_chars/lines,
  n_functions, has_try, n_imports, s0 토큰·$. 히든·canonical 무관. (`benchmark/features.py`)
- P2: 표준화, L2 λ = **1.0**, IRLS 8, K=5 겹 × R=20 셔플, 특징 순열 2000, 과제 부트스트랩 1000. 주 분석 = **P2-post**(pre+post). 부차 = P2-pre, P1(진단).

## 4. 판정 (사전 등록)
- **R2**: 특징 순열 p < 0.05 ∧ **P2-post 정책 이득 점추정 ≥ 10pp** → **통과**. 그 외 **미확인**. ("없음" 결론은 쓰지 않는다.)
- 검정력: "80% 검정력은 참 정책 이득 ≥ 12pp 근처 (N=150, ρ=0.7, H3 17/20 [62, 97])" — N=200 확인 집합에서 참 12pp 이면 통과율 60~70% (H3 12~14/20).
  참 6pp 는 통과하지 않는다. 10pp 는 실용 문턱이다.
- 부차 보고: P2-pre 이득, P2-post − P2-pre(실행 후 신호의 추가 가치), P1 이득, oracle gap(기술 통계, 상한 아님), arm 별 성공률·$·거부율, 정책이 고른 arm 분포와 $,
  ρ̂(뒤집힘 부분집합), 예산 매칭(정책 $ vs 고정 $).
- 통과 시 다음(4~6주차): "같은 데이터에서 REDEREF 식 사후분포 라우터와 반사실 실측(정책이 고른 arm 만 실행)을 비교한다."
- 미확인 시 결론 문장: "BCB 적격 풀 N=200 에서, 사전 등록한 특징과 학습기로는 결정 시점 신호 기반 정책이 최선 고정 전략을 10pp 이상 이긴다는 증거를 얻지 못했다
  (미확인; 참 이득이 12pp 미만이거나 특징이 유형을 담지 못한 경우를 구별하지 못한다)."

## 5. 비용·중단
- 상한 $14 = 탐색 59 × 6 arm × ≈$0.04 ≈ $2.4 + 뒤집힘 30 × 2 arm × 1회 ≈ $0.5 (여유 포함 $4) + 확인 200 × ≈$0.04 = $8 (여유 포함 $10).
- 중단: 원장 예약 거부·커밋 후 초과·미측정 비용·인프라 장애(infra=True) → 부분 결과 저장, 종료 코드 2, 재개는 멱등 재실행(`result.json` 건너뜀).
