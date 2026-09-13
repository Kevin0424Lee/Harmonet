# 2~3주차 실험 설계 (C2 개정, 2026-09-13) — 실행하지 않음

상태: **사전 등록 대상.** 숫자로 적힌 통과 기준은 실행 전 고정하고 이후 바꾸지 않는다. C1(초안) 대비 바뀐 점은 각 절 머리에 표시.

## 0. 실험 질문

> 같은 작업 상태 s 에서 (i) 종료, (ii) 같은 에이전트의 자기 수정, (iii) 다른 모델의 전문가 추가 — 셋 중 어느 것이 나은지가
> **실제로 갈리는 경우가**, 예산을 맞춘 조건에서, 노이즈 바닥 위로 **존재하는가?**

방법 비교가 아니라 전제의 존재 검증이다(`related_work_week1.md` §3). 갈림이 없으면 REDEREF 대비 차이는 기여가 아니다.

**기준선의 의미 (C2 추가).** 비교 기준선은 "과제와 무관하게 하나의 arm 을 항상 고르는 최선 고정 전략"이다. 이것은 REDEREF·KABB 류의
**에이전트 수준 사후분포가 수렴했을 때 도달하는 정책**과 같다 — 그들은 에이전트 이력만 조건으로 쓰므로 상태 s 를 보지 않고 한 arm 으로 수렴한다.
따라서 `oracle(상태 조건부 최선) − 최선 고정 전략` 의 gap 은 **상태 조건부 가치의 상한**이다: 어떤 상태 조건부 정책도 이 gap 보다 더 벌 수 없다.
gap 이 0 에 가까우면 상태를 보는 정책을 만들 이유가 없다.

## 1. 트랙과 태스크 (C2 개정)

| 트랙 | 풀 | 용도 | 규칙 |
|---|---|---|---|
| **functional 트랙 (주)** | **§1-A 프로브로 확정될 풀** — HumanEval 은 부적격(A 단독 96.3%, `evidence/week2/pool_probe.md`), MBPP 는 히든 없음(A7c). 후보: LiveCodeBench medium(2025-01 이후, public/private 분리), BigCodeBench-Hard | 탐색 + 확인 | 탐색용과 **확인용 ≥ 200 문제**를 인덱스로 동결(`evidence/week2/confirm_ids.json`). 확인용은 2주차에 생성·평가·열람 금지 |
| SWE 트랙 (보조) | SWE-bench Lite 0–29 | **탐색 파일럿만** | 가시 검증이 `apply` 수준이라 functional 신호 없음. 결과는 방향 참고 |
| SWE 보존 | SWE-bench Lite 30–59 | **외적 대조** | 30개는 Δ=10pp 를 검출할 검정력이 없다 — 통과/실패 판정에 쓰지 않고 functional 트랙 결론이 SWE 에서도 같은 방향인지만 본다 |

### 1-A. 풀 확정 절차 (사전 등록)
A 단독(`claude-haiku-4-5`, single, 1회) 히든 통과율이 **[30%, 70%]** 안이어야 채택. 후보마다 프로브 ≈ $0.5. 확정 전에는 arm 실험을 시작하지 않는다.
LiveCodeBench 는 난이도 층(easy/medium/hard)별로 통과율이 크게 갈리므로 층을 고정한 뒤 프로브한다.

**전문가가 이길 과제만 사후 선별하지 않는다.** 집합은 인덱스로 고정, 생성 실패도 분모에 남는다.

## 2. 실험 arm (C2 개정: A-self×k 추가, 용어 정정)

A = builder 모델, B = A 와 다른 모델(§5). s0 = A 가 1회 build 하고 `verify_visible` 을 돌린 직후 상태 (§7 스냅샷).

| arm | s0 이후 행동 | 모델 | 프롬프트 | 무엇을 분리하는가 |
|---|---|---|---|---|
| **T** terminate | 없음. s0 의 산출물 제출 | — | — | 기준. A-solo 와 동일 실행 |
| **A-self** self_revise ×1 | A 가 산출물 + 가시 검증 출력을 보고 1회 수정 | A | builder | 자기 수정 1회 |
| **A-self×k** self_revise ×k | 같은 것을 예산이 허용하는 만큼 반복, **k = floor(b_cont / A 1회 비용 중앙값)** | A | builder | 같은 $ 로 자기 수정을 여러 번 — B-expert 와 **$ 매칭된** 자기 수정 |
| **A-role** expert-role | A 가 **reviewer 프롬프트**로 리뷰·수정 | A | reviewer | 전문가 프롬프트를 같은 모델에 옮긴 대조군 |
| **B-expert** expert_review | B 가 reviewer 프롬프트로 리뷰·수정 | B | reviewer | A-role 과의 차이 = **같은 reviewer 프롬프트에서 A→B 교체 효과** (C1 의 "모델 이질성의 순기여"를 이 표현으로 정정) |
| **B-solo** | B 가 처음부터 build (s0 미사용) | B | builder | 협업이 아니라 더 좋은 모델만 썼을 때 |
| A-solo | = T | A | builder | 표에 병기 |

전 arm 동일 정보·도구: 산출물, `verify_visible` 출력 전문, 과제 프롬프트, 같은 `spec`. 히든 정보 없음(§6). v1 키워드 repair·`eval_repair` 비활성.

## 3. 예산 (C2 개정: max_tokens 규칙, 거부율)

- **주 예산 = USD**, `harmonet/pricing.py` `prices_2026-09` 스냅샷. 토큰·wall_ms 는 항상 함께 보고.
- 계속 arm 의 추가 예산 상한 **b_cont** = 파일럿에서 잰 B-expert 1회 호출 비용의 중앙값. B-solo 는 T + b_cont.
- **호출 규칙 (사전 등록):** 호출 직전 `max_tokens = floor((잔여 예산 − 입력 비용) / 출력 단가)`. 이 값이 **< 256 이면 호출하지 않고** 기존 산출물을 제출하며 `budget_refused=true` 로 기록. 호출하면 그 max_tokens 로 실행.
- **예산 강제 소진 없음.** arm 별 **거부율**(budget_refused 비율)을 보고한다 — 거부율이 높은 arm 의 성공률은 그 자체로 해석 대상.
- 보고: 이득 / 실제 지출 / 거부율, arm 별.

## 4. 반복·기준선·판정 (C2 전면 개정)

1. **반복 단위 = 같은 s0.** 과제 → s0 **1개 고정** → 각 arm 을 s0 에서 **k회** 실행. 반복은 arm 실행의 표본 노이즈를 재는 것이지 초기 상태 다양성이 아니다.
   초기 상태 다양성(여러 s0)은 **별도 층**으로, 여력이 있을 때만 s0 을 2개 이상 만들어 층으로 나눠 보고한다.
2. **기준선 = 최선 고정 전략.** 반복 집합 1 에서 arm 별 평균 히든 성공률을 구해 가장 높은 arm 하나를 고른다(과제와 무관).
3. **통계량 = 교차 적합 oracle − 교차 적합 최선 고정.**
   - oracle: 과제별 최선 arm 을 **집합 1** 에서 고르고 **집합 2** 에서 그 arm 의 성공률을 평가.
   - 최선 고정: 집합 1 에서 고른 하나의 arm 을 집합 2 에서 평가.
   - gap = 두 값의 차 (집합 2 기준). 집합 1↔2 를 바꿔 한 번 더 구하고 평균.
4. **판정 = 과제 단위 부트스트랩 95% CI** (n = 과제 수, 반복은 과제 안에 중첩, 10,000회).
   - **통과:** CI 하한 > 0 **∧** 점추정 ≥ **10pp**
   - **보류:** 점추정 ≥ 10pp ∧ CI ∋ 0 → 표본 부족. N 을 늘려 재시도 (확인용 집합은 1회만이므로 탐색용에서 재산정)
   - **실패:** 그 외
   - (C1 의 순열 검정과 "뒤집힘 < 이득/2" 기준은 삭제. 반복 간 뒤집힘은 **기술통계**로만 보고.)
5. **N 산정:** 파일럿(탐색용, k=3)의 과제 단위 분산과 Δ=10pp, α=0.05, power 0.8 로 확인용 N 을 계산해 `evidence/week2/power.json`. 확인용 동결 집합(≥200)이 N 을 넘으면 "검출 불가"로 보고.
6. **주 기준 = 히든 성공률.** **부기** = arm 별 (성공률, 실제 $ 평균, 거부율), 그리고 **성공한 arm 중 최저 비용**(과제별로 성공한 arm 들의 $ 최소값의 평균 — "얼마에 살 수 있었나").

## 5. 모델과 비용

| 역할 | 모델 | 단가 | 근거 |
|---|---|---|---|
| A | `claude-haiku-4-5` | $1 / $5 per MTok | 프로브·9월 실행과 동일 계열 |
| B | `claude-sonnet-4-6` | $3 / $15 | 같은 API, 명백히 다른 모델 |

비용 추산(파일럿, 탐색용 N_e 문제 × k=3, arm 6): 문제당 프롬프트 ~1.5k(LiveCodeBench) ~ 4k(SWE) 토큰.
- functional 트랙 N_e=60: s0 생성 $0.3 + A 계열 3 arm $0.9 + B 계열 2 arm $3.0 ≈ **$4.2**; 확인용 200 × k: ≈ $14 × k.
- SWE 파일럿 30 × 3: ≈ $9.4 (C1 추산 유지).
정확한 값은 b_cont 확정 후 갱신.

## 6. 검증기 위치 (§15) — 루프 안은 `verify_visible` 뿐, `score_hidden` 은 에피소드 종료 후

```mermaid
flowchart LR
    P[과제 프롬프트 + spec] --> A0[A: build]
    A0 --> VV[verify_visible<br/>공개 테스트 / apply-check<br/>level: static·apply·functional]
    VV --> S[(스냅샷 s0<br/>artifact + verify 출력 + 프롬프트 컨텍스트<br/>snapshot_ref)]
    S --> T[T: terminate]
    S --> AS[A-self ×1 / ×k]
    S --> AR[A-role: reviewer 프롬프트, 모델 A]
    S --> BE[B-expert: reviewer 프롬프트, 모델 B]
    P --> BS[B-solo: build from scratch]
    AS --> VV2[verify_visible]
    AR --> VV2
    BE --> VV2
    BS --> VV2
    T --> END[에피소드 종료<br/>trace.save]
    VV2 --> END
    END --> SH[score_hidden<br/>private 테스트 / SWE 하네스<br/>TaskState.score, trigger=post_hoc]
    style SH fill:#fdd,stroke:#900
    style VV fill:#dfd,stroke:#090
    style VV2 fill:#dfd,stroke:#090
```

초록 = 루프 안에서 볼 수 있는 유일한 신호. 빨강 = 종료 후에만. `TaskState.score` 가 채워진 뒤 Action 이 추가되면 `save()` 가 거부(A7).
LiveCodeBench 는 public/private 가 필드로 분리돼 있어 이 그림과 정확히 대응한다. SWE 는 가시 검증이 `apply` 까지.

## 7. 분기 스냅샷 (§9)

- s0 = `evidence/week2/<run_id>/<task_id>/s0/` : `artifact.{py,diff}`, `verify_visible.json`, `prompt_context.json`(과제 프롬프트, spec, 시스템 프롬프트, 모델 A id), `decision_signals.json`(§8).
- 모든 계속 arm 은 **디스크의 s0 를 읽어** 재개(메모리 상태 재사용 금지). arm 실행 순서는 과제별 무작위.
- `Action.input_ref` / `Action.output_ref` = 읽은/쓴 파일 경로. `result_summary` 400자는 보조.
- 구현은 2주차 첫날. 이번 주 코드 없음.

## 8. 결정 시점 신호 — 기록만 (§14)

s0 에서 `decision_signals.json` 에 기록, **2주차에는 분석하지 않는다**: `verify_visible.outcome/level/n_run/n_passed/n_failed/flags/applied`, 오류 종류, 산출물 길이(chars/lines), 진단 텍스트(오류 tail 300자), A build 비용(토큰·$·wall_ms), 프롬프트 길이, `budget_refused`.

## 9. 공정성

- 전 arm 동일: 히든 없음, temperature 0.2, 같은 spec, 같은 가시 검증 출력. SWE 는 oracle 파일 컨텍스트·hints 없음·4096.
- A-role 없이는 B-expert 의 이득에서 프롬프트 효과를 뺄 수 없다. A-self×k 없이는 B-expert 의 이득이 "돈을 더 썼기 때문"인지 뺄 수 없다.
- v1 산출물은 코드 블록 없이 나와 `heuristic` 추출됐다(RESCORE.md §3). arm 에서는 builder 프롬프트에 fenced 출력을 요구하고 `extraction` 을 기록.

## 10. 실행 환경

- `HARMONET_ALLOW_NO_REDIS=1`, `HARMONET_LLM_BACKEND=anthropic`, `HARMONET_MODEL_BUILDER=claude-haiku-4-5`, `HARMONET_MODEL_REVIEWER=claude-sonnet-4-6`, `ANTHROPIC_MAX_TOKENS`(§3 규칙으로 호출별 설정), `ANTHROPIC_TEMPERATURE=0.2`, `HARMONET_TRACE_RUN_ID=week2_pilot_<date>`, `G1_DISABLE_EVAL_REPAIR` 기본.
- functional 채점: `verify.score_hidden`(A7b 하네스, subprocess). SWE 채점: WSL swebench 하네스.
- 실험 전 `python -X utf8 scripts/week1_smoke.py` 통과 필수.

## 11. 2주차 첫 작업

1. 풀 프로브(LiveCodeBench medium 2025-01+ 우선, ≈$0.5) → [30%,70%] 판정 → 풀 확정. 로더: public/private 테스트를 `spec["tests"]/["hidden_tests"]` 로, stdin/stdout 러너를 하네스에 추가.
2. `snapshot_ref` / `input_ref` / `output_ref` / `budget_refused` 구현 + `benchmark/arms.py`(6 arm, §3 예산 규칙).
3. 확인용 ≥200 ID 동결(열람 없이 ID 만).
4. 파일럿 k=3 → b_cont·`power.json` → N 판정.

## 12. 하지 않는 것

- 학습 규칙(밴딧·사후분포·위상 갱신) — 3주차 이후, §0 의 gap 이 통과했을 때만.
- 결정 시점 신호 분석 — 3주차.
- 확인용 집합 접근 — 3주차 1회. SWE 30–59 는 검정력 없는 외적 대조로만.
