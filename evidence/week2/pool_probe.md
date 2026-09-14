# 후보 풀 천장 프로브 — 사전 등록 (2026-09-13, 실행 전 작성)

## 사전 등록
- **기준:** A 단독(`claude-haiku-4-5`, single 어댑터, 1회 호출)의 **히든 통과율이 [30%, 70%] 밖이면 그 풀은 주 트랙 부적격.**
  - 70% 초과 → 천장 효과: 계속 arm 의 이득이 나올 여지가 없음.
  - 30% 미만 → 바닥 효과: s 자체가 쓸모없는 산출물.
- **풀:** HumanEval 164 (전체). 채점: `verify.score_hidden` (하네스 result.json + nonce), 히든 = `check(entry_point)`.
- **설정:** temperature 0.2, max_tokens 4096, hints 없음, 반복 1회. 비용 상한 ≈ $0.5.
- **판정은 실행 전에 고정한다.** 결과를 보고 구간을 바꾸지 않는다.

## 결과 (2026-09-13 실행)
- `claude-haiku-4-5` single, HumanEval 164, 히든 = `check(entry_point)`, 하네스 채점: **158/164 = 96.3%** (95% CI ±2.9).
  outcome pass 158 / fail 4 / error 2. 실패: HumanEval/93, 127, 130, 132, 145, 160. 추출 fenced 164/164, token_source measured 164/164.
- 비용: prompt 35,605 / completion 41,603 토큰 = **$0.244**. 파일: `pool_probe_humaneval164.{csv,json}`, 로그 `probe_run.txt`, trace `evidence/traces/pool_probe_humaneval164/single/`.

## 판정 (사전 등록 기준 적용)
**96.3% > 70% → HumanEval 은 주 트랙 부적격 (천장 효과).** A 단독이 거의 다 풀어서 계속 arm 의 이득이 나올 여지가 6/164 뿐이다.
MBPP 는 히든이 없어(A7c) 애초에 부적격. 따라서 functional 트랙의 풀은 아래 후보 중에서 골라야 한다.

## 후보 풀 로더 비용 추산 (실행 전 조사만)

| 풀 | 규모 | 테스트 형식 | 히든 분리 | 로더 비용 | 채점 환경 비용 | 예상 A 단독 통과율 (근거) |
|---|---|---|---|---|---|---|
| **BigCodeBench-Hard** (HF `bigcode/bigcodebench-hard`, v0.1.4) | 148 | `unittest` 클래스 (`test` 필드), `entry_point`, `libs` | 테스트 전문이 데이터에 있고 프롬프트(`instruct_prompt`)에는 없음 → 히든으로 사용 가능. 공개 테스트는 없음 → 가시 검증은 `doc_struct` 예제/정적 검사 수준 | `datasets` 로 parquet 로드 (이미 설치). unittest 러너를 하네스에 추가(테스트 개별 실행 대신 클래스 단위 → n_run = 테스트 메서드 수로 집계) ≈ 0.5일 | **높음**: 테스트가 pandas·sklearn·matplotlib·flask·requests 등 수십 개 서드파티에 의존. 격리 실행에는 전용 Docker 이미지(공식 `bigcodebench/bigcodebench-evaluate`) 필요, 로컬 pip 설치는 충돌 위험 | 공식 리더보드 기준 haiku 급 모델 20~35% (Hard) — **구간 안** |
| **LiveCodeBench** (HF `livecodebench/code_generation_lite`, release_v5/v6) | 400~880 | stdin/stdout 테스트 (`public_test_cases` / `private_test_cases`), `starter_code` | public/private 가 필드로 분리 → 가시 = public, 히든 = private. 가장 깔끔 | 커스텀 로딩 스크립트(`trust_remote_code`), private 테스트는 인코딩돼 있어 디코딩 필요; stdin/stdout 러너를 하네스에 추가 ≈ 0.5~1일 | **낮음**: 표준 라이브러리만. subprocess 샌드박스로 충분 | 난이도별 편차 큼: easy 70%+, medium 30~50%, hard <20% — **medium 만 쓰면 구간 안** 가능. 시간 오염 회피 위해 2025-01 이후 문제만 |

권고(승인 대상): **LiveCodeBench medium(2025-01 이후)** 를 1순위 — public/private 분리가 설계(§15)와 정확히 맞고 채점 환경이 가볍다. 실제 통과율은 같은 프로브($≈0.5)로 재확인 후 [30%,70%] 판정.

---

# 프로브 2 사전 등록 — LiveCodeBench (2026-09-13, 실행 전 작성)

## 풀
- `livecodebench/code_generation_lite`, revision `0fe84c3912ea0c4d4a78037083943e8f0c4dd505`, release `release_v6` (파일 test5.jsonl·test6.jsonl = 2024-09~2025-04),
  testtype=stdin, difficulty=medium, contest_date ≥ 2025-01-01.
- 추출: seed 20260913, N_probe = 60 (필터 후 60 미만이면 전부). 문제 ID: `probe_ids_lcb_medium_2025.json`.
- 모델·설정: claude-haiku-4-5 single 1회, temperature 0.2, max_tokens 4096, hints 없음. 채점: `score_hidden`(private). 판정 [30%, 70%].
- 층 순서(고정): medium > 70% → hard 재프로브. medium < 30% → easy+medium 1:1 재프로브. 그래도 밖 → LCB 보류, EvalPlus 로 이동. 재프로브도 각각 사전 등록 후.
- 프로브에 쓴 문제는 확인용에서 제외. 확인용 ≥200 이 남는지 **실행 전 확인**. 결론은 이 풀(필터·날짜·난이도)에만 적용. 비용 상한 $1.

## 실행 전 확인 (필터 후 문제 수) — **프로브 미실행**

test5+test6 stdin 217개, 난이도 × 월:

| difficulty | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 | 2025-04 | total |
|---|---|---|---|---|---|---|---|---|---|
| easy | 0 | 7 | 10 | 7 | 8 | 8 | 8 | 2 | 50 |
| medium | 0 | 9 | 7 | 8 | 7 | 6 | 11 | 2 | 50 |
| hard | 3 | 21 | 20 | 13 | 15 | 17 | 22 | 6 | 117 |

contest_date ≥ 2025-01-01 (stdin 112개):

| difficulty | 2025-01 | 2025-02 | 2025-03 | 2025-04 | total |
|---|---|---|---|---|---|
| easy | 8 | 8 | 8 | 2 | 26 |
| medium | 7 | 6 | 11 | 2 | 26 |
| hard | 15 | 17 | 22 | 6 | 60 |

- 사전 등록 필터(medium · 2025-01-01+)로 남는 문제: **26개**. N_probe 60 미만 → 전부 사용 가정 시 **확인용 0개** (≥200 필요).
- 2025+ 전 난이도를 합쳐도 112개, 난이도·날짜 무관 stdin 전체도 217개 → **이 풀에서는 어떤 층 조합으로도 확인용 ≥200 을 확보할 수 없다.**
- 규칙("안 남으면 프로브를 실행하지 말고 보고")에 따라 **프로브를 실행하지 않았다.** 비용 $0.

## 다음 사전 등록 후보 (승인 필요 — 어느 것도 실행하지 않음)
1. **확인용 규모 재설정**: LCB 2025+ stdin 전 난이도 112개 중 프로브 60 → 확인용 52. Δ=10pp 검정력이 안 나올 가능성이 크므로 §4.5 "검정력 부족" 보고를 전제로 진행.
2. **날짜 완화**: 2024-10+ stdin 217개 (medium 50). haiku-4-5 학습 데이터 오염 가능성(컷오프 이전 문제) 을 한계로 명시해야 함.
3. **EvalPlus(HumanEval+/MBPP+) 로 이동**: 층 순서의 최종 대안. HumanEval+ 는 **164개로 표본 조건(확인용 ≥200) 미달**이라 제외 (천장이라서가 아님 — 96.3% 는 HumanEval 결과). MBPP+ 378개는 확인용 ≥200 확보 가능. 로더 비용: `pip install evalplus`, plus_input 기대 출력은 canonical 실행으로 생성. **한계: 추가 테스트가 비공개라는 것 ≠ 사전학습 오염 없음** — MBPP 문제 자체는 2021년 공개돼 학습 데이터에 있을 수 있다.
4. **release_v1~v4(2023-05~2024-09) 포함**: 문제 수는 충분하지만 오염 위험이 가장 큼 — 권하지 않음.

---

# 프로브 3 사전 등록 — MBPP+ (2026-09-14, 실행 전 작성)

사용자 결정(2026-09-13): 주 트랙 = MBPP+, 확인용 ≥200 유지, LCB 는 보조로 강등, HumanEval+ 는 표본 조건(164) 미달로 제외.

## 풀
- MBPP+ v0.2.0, evalplus 0.3.1, 데이터 sha256 `ee1701c9…` / 스펙 sha256 `b6888ff4…` (`mbppplus_source.md`).
- 제외 후 345개 → 프로브 60개 = `probe_ids_mbppplus.json` (seed 20260913, 커밋에 동결) → 확인용 285개 = `confirm_ids_mbppplus.json` (주 2 에서 손대지 않음).

## 조건
- 어댑터 single (`benchmark/mbppplus_g1.py`): builder 1회 호출 → 코드 추출 → verify_visible(base) → 종료 → score_hidden(plus−base).
- 모델 claude-haiku-4-5, temperature 0.2, max_tokens 4096, 시스템 프롬프트 `_DEFAULT_SYSTEM`, 과제 프롬프트 = 공식 MBPP+ prompt + 코드블록 지시.
- 판정 지표: **plus_only_pass** (히든 plus−base 통과율). base_pass·both_pass 는 함께 보고하되 판정에 쓰지 않는다.
- 판정 규칙: plus_only_pass ∈ [30%, 70%] → 이 풀 채택(pass). 밖 → 채택 안 함(unconfirmed) — 다음 사전 등록만 쓰고 멈춤 (재프로브 실행 금지).
- 비용 상한 $1 (HumanEval 164개가 $0.13 였으므로 60개 ≈ $0.05 예상). 초과 시 중단.
- 보고 항목: pass/fail/error/timeout 분포, base_pass·plus_only_pass·both_pass, 비용, extraction 종류, token_source (measured 여야 함), trigger=eval:hidden 0건.

## 결과 (2026-09-14 실행) — 파일 `pool_probe_mbppplus.{json,csv}`, 로그 `probe_mbppplus_run.txt`, trace `evidence/traces/pool_probe_mbppplus/`
- `claude-haiku-4-5-20251001` single, MBPP+ 프로브 60: **plus_only_pass 51/60 = 85.0%** (Wilson 95% [73.9, 91.9]).
  base_pass 55/60 = 91.7% [81.9, 96.4], both_pass 51/60 = 85.0%. outcome pass 51 / fail 9 / error 0 / timeout 0.
- 실패 9: base 통과·plus 만 실패 4 (109, 113, 589, 639 — 히든 102~121개 중 4~39개 실패), base 도 실패 5 (124, 160, 235, 430, 773). 430 은 ZeroDivisionError.
- 추출 fenced 60/60, token_source measured 60/60, trace 60개 중 trigger=eval:hidden **0건**, score.trigger=post_hoc 60/60.
- 비용: prompt 8,277 / completion 6,040 토큰 = **$0.039** (상한 $1). 실행 중 `cost_usd=None`(price_unknown) — API 응답 model id 에 날짜가 붙어
  가격표 별칭과 안 맞았다. 실행 후 pricing 을 고쳐(90498eb) 같은 토큰으로 사후 계산해 `cost_usd_posthoc` 로 기록. 요약의 `cost_usd` 는 **None**(n_unpriced 60) — 0 이 아니다(B2 1-3 정정). trace 파일은 손대지 않았다.

## 판정 (사전 등록 기준 적용)
**85.0% > 70% → unconfirmed.** 상한 CI 하단 73.9% 도 70% 를 넘는다. MBPP+ 는 이 모델·이 프롬프트에서 천장 구간이다. 사전 등록대로
**재프로브를 실행하지 않고** 아래 다음 후보만 적는다. 확인 집합(`confirm_ids_mbppplus.json` 285)은 그대로 동결 — 채택 여부는 사용자 결정.

## 다음 사전 등록 후보 (승인 필요 — 어느 것도 실행하지 않음)
1. **MBPP+ 를 천장 경고와 함께 채택**: 나머지 arm 이 올릴 수 있는 폭이 ≤15pp 라 Δ=10pp 검정은 가능하나 "A 단독이 거의 다 푼다" 는 해석 한계를 명시해야 한다.
   [30, 70] 규칙을 바꾸는 것이므로 사용자 결정 사항. 비용 0 (프로브 재실행 없음).
2. **BigCodeBench (Full 1,140 / Hard 148)**: 라이브러리 호출·긴 사양 과제로 haiku 급 모델의 공개 pass@1 이 40~50% 대. 확인용 ≥200 확보 가능(Full).
   비용: 로더 + 공식 하네스(의존 패키지 수십 개, Docker 권장) 전사 필요 — MBPP+ 때와 같은 동등성 테스트·정답 전수 확인 절차. 프로브 60 ≈ $0.2.
3. **LCB 2024-10+ stdin 217개** (프로브 2 후보 2): 확인용 157 (<200) 이고 컷오프 이전 문제라 오염 경고 필요.
4. **MBPP+ ∪ LCB 2025+ 혼합 풀**: 표본은 되지만 두 벤치마크의 판정 규칙·난이도가 달라 층별 보고가 강제된다 — 권하지 않음.
권장: 2 (BigCodeBench) 를 다음 프로브로, 그 전까지 MBPP+ 확인 집합은 보조로 유지.

---

# 프로브 4 사전 등록 — BigCodeBench Complete (2026-09-14, 실행 전 작성)

결정(코덱스, 2026-09-14): 주 트랙 후보 = BCB Full 1,140 (Hard 148 은 표본 조건 미달). MBPP+ 는 채택하지 않고 보존(확인 285 봉인 유지).
LCB 날짜 완화 안 함. BCB 가 관문을 못 넘으면 데이터셋을 더 추가하지 않고 교수님 재검토용 정리로 전환.

## 풀 (Week2-C0, `bcb_source.md`)
- 적격 집합 409 = 관문 1(가시 doctest, canonical 2회 pass) 412 ∧ 관문 2(공식 test, canonical 2회 pass) 410 − 개발용 ID.
- 프로브 60 = `probe_ids_bcb.json` (seed 20260913, 커밋에 동결). 확인 집합 = 나머지 349 (≥200) — 프로브 통과 시 동결.
- 제외: 개발용 BigCodeBench/0·1·2.

## 조건
- A = claude-haiku-4-5, B = claude-sonnet-4-6. 각 single 1회 (`benchmark/bcb_g1.py`), temperature 0.2, max_tokens 4096, 시스템 프롬프트 `_DEFAULT_SYSTEM`.
- 프롬프트 = `complete_prompt` 그대로 (가시 예제는 docstring 에 이미 포함).
- 루프 안 가시 검증 = doctest TestCases (공식 이미지, 공식 untrusted_check). 채점 = 공식 이미지에서 공식 `test` 모듈, post_hoc (trigger=eval:hidden 0건이어야 함).
- **판정**: A 의 히든 통과율 ∈ [30%, 70%] ∧ B 의 히든 통과율 ≤ 70% → pass (풀 확정, 확인 349 동결, 프로브 60 은 탐색 후보). 아니면 unconfirmed.
  공개 리더보드 수치는 예상치로 쓰지 않는다.
- 비용 상한 $1 (두 모델 합). B2 1-3 사전 점검(모델 조회 → 보고 id 정규화 → 가격표) 통과 필수; 실행 중 미측정 발생 시 다음 호출 중단.
- 보고: A/B 성공률과 Wilson 95% CI, outcome(pass/fail/error/timeout) 분포, 가시 테스트 통과율(참고), extraction, token_source, cost_usd(None 없어야 함).
- 실패 시: 추가 데이터셋 없음. "연구 질문·실험 설정 재검토" 초안(프로브 4개 결과표 + 조건 + 무엇이 안 맞는지)만 쓰고 멈춤.

## 결과 (2026-09-14 실행) — 파일 `pool_probe_bcb_{A,B}.{json,csv}`, 로그 `probe_bcb_{A,B}_run.txt`, trace `evidence/traces/pool_probe_bcb_{A,B}/`

| arm | 모델 (응답 id) | 히든 통과 (공식 test, post_hoc) | Wilson 95% | 가시 doctest 통과 (참고) | outcome | 비용 | 토큰 (prompt/completion) |
|---|---|---|---|---|---|---|---|
| A | claude-haiku-4-5-20251001 | **38/60 = 63.3%** | [50.7, 74.4] | 48/60 = 80.0% | pass 38 / fail 22 / error 0 / timeout 0 | $0.184 | 22,596 / 32,274 |
| B | claude-sonnet-4-6 | **45/60 = 75.0%** | [62.8, 84.2] | 54/60 = 90.0% | pass 45 / fail 15 / error 0 / timeout 0 | $0.387 | 22,656 / 21,237 |

- extraction fenced 120/120, token_source measured 120/120, cost_usd None 0건(사전 점검 통과), trigger=eval:hidden 0건, score.trigger=post_hoc 120/120.
- 합계 $0.570 (상한 $1). 가시→히든: A 는 가시 pass 인데 히든 fail 13, 가시 fail 인데 히든 pass 3; B 는 10 / 1 — 가시 doctest 는 약한 신호(참고용).
- 과제별 교차: 둘 다 pass 36, A 만 2, B 만 9, 둘 다 fail 13.

## 판정 (사전 등록 기준 적용)
A 63.3% ∈ [30, 70] **충족**. B 75.0% > 70% **미충족** (CI 하단 62.8% 는 70% 아래이므로 표본 60 으로는 B 가 70% 를 넘는다고 단정할 수 없으나,
사전 등록 규칙은 점추정치 기준이고 재프로브를 허용하지 않는다). → **unconfirmed.**
사전 등록대로 확인 집합을 동결하지 않고, 데이터셋을 더 추가하지 않으며, 재검토 초안(`docs/week2_review_draft.md`)만 쓰고 멈춘다.

## D2 ⑤ 재적격성 기록 (2026-09-14, 프로브 결과·판정은 그대로)
- 정적 필터 v1 → v2 (`benchmark/bcb.py::FILTER_VERSION = nondet-v2`): v1 정규식은 `open\(` 뒤에 `\b` 를 요구해 `open('x')`/`Path('x')`/`input()`
  호출을 못 잡았다. v2 는 호출 패턴을 `\b` 없이 두고 `os.path.*(` / `shutil.*(` / `tempfile.*(` 를 추가. 정적 통과 637 → 630.
- 채점기 D2 (`harmonet/bcb_check.py` d2.1: 실행 수 검사 + 사전 바인딩 + exitcode) 로 적격성 배치도 재실행 (캐시 키 = revision·이미지 digest·필터·채점기 버전).
- 적격 풀에서 빠진 ID: **BigCodeBench/565, 817** (필터 v2 — 예제가 `open(` 을 씀), **721** (D2: test 모듈이 후보 없이 로드되지 않아 기대 테스트 수를
  못 세므로 채점 불가 → 제외), 개발용 추가 **3, 4, 9** (D5 arms 스모크). 관문 1 412 → 411, 관문 2 410 → 408, 적격 409 → **404**.
  반복 간 불안정으로 뒤집힌 canonical 판정 7건 (`benchmark_data/bcb/work/results_v1_c0.json` 대 v2): 205·459·1040 은 v2 에서 pass, 227·594 는 v2 에서
  fail(D2 기대 수 계수 실패), 497 doctest 가 v2 에서 pass, 721 위.
- 프로브 60 중 재적격성에서 빠지는 ID: **565 (1개)**. 프로브 결과 자체는 사전 등록 판정 그대로 두고, 재적격성 적용 시:
  **A 38/59 = 64.4%, B 44/59 = 74.6%** (565 는 A fail / B pass) — 판정 방향 불변.
- 재채점(RESCORE_bcb.md): D2.1 채점기로 120 후보 재채점, 뒤집힌 행 0.

## F5 기록 정정 (2026-09-15): BigCodeBench/497 원인, 적격 조건 강화, 풀 재집계
- **497 원인**: doctest 예제 `>>> task_func()` → `'Monday'`, `>>> task_func(3)` → `'Friday'` 가 **실행 당일 요일**에 의존한다 (canonical 이
  `datetime.now(pytz.UTC)` 의 요일을 돌려줌; 예제 텍스트에는 datetime 토큰이 없어 정적 스크린을 통과). C0 배치는 2026-09-13 UTC 일요일에 돌아
  fail/fail, D2 배치는 09-14 UTC 월요일에 돌아 pass/pass. 이미지·필터 변경과 무관. → **flaky(날짜 의존) 로 제외.**
- **적격 조건 강화**: "R=3 회 실행 전부 pass ∧ 이력(`benchmark_data/bcb/work/eligibility_history.json`, C0·D2·이번 실행 누적)의 어느 실행에서도 non-pass
  없음". 캐시 키에 반복 수 포함. 이번 실행(3회, 1,820s): 관문 1 411, 관문 2 408, 이력 안정 407, 개발용 6 제외 → **적격 403**.
- **차집합 (C0 409 → 403)**: −6 = 565·817(필터 v2), 721(D2 기대 테스트 수 계수 불가), 3·4·9(개발용). +1 이었던 497 은 flaky 로 다시 제외 → 순 +0.
- **미사용 확인 후보**: 프로브 60 은 재적격성과 무관하게 전부 제외 → 403 − 59(프로브 중 적격 59; 565 는 이미 제외) = **344** (이전 표기 349 는 C0 시점 409 − 60).
  확인 집합은 여전히 동결하지 않는다(교수님 판단 대기). 재적격성 적용 시 프로브 A 38/59, B 44/59 는 D2 ⑤ 기록과 같다.
