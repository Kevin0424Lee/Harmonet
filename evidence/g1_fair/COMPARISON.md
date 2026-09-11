# G1 재측정 — 전 시스템 동일 기준 토큰 비교 (2026-09-11)

## 결론 먼저

- **LangGraph 대비 우위는 유지된다.** 같은 모델·같은 엔드포인트·같은 집계 기준(API `usage`)으로
  HarmoNet v2는 LangGraph보다 토큰을 **75.5% 적게** 쓴다 (수리 포함 313 vs 1278). 수리 제외 조건에서는 78.5%.
- **CrewAI 대비 우위는 뒤집히지 않았다 — 하지만 예상과 다른 이유다.** 구 측정의 CrewAI 값(295)은
  "API 실측"이 아니라 단어수 추정이었음이 이번에 확인됐다(아래 §2). 실측하면 CrewAI는 995로, HarmoNet v2(313)의 약 3.2배다.
- **정확도는 5개 시스템이 92.5~95.0%로 사실상 동률이다.** 차이(±2.5pp)는 95% 신뢰구간(±4~5pp) 안이다.
  7B 모델에서도 변별력은 거의 나오지 않았다 — 전 시스템이 공통으로 틀리는 문제(HumanEval/10, mbpp_20)가 실패의 대부분이다.
- **토큰 격차의 주된 원인은 호출 횟수다.** 베이스라인 3개는 고정 3회 호출(architect→builder→validator),
  HarmoNet v2는 평균 1.13회(builder 1회 + 정적 검증 실패 시에만 escalation). 논문에서는 이 점을 함께 서술해야 한다.
- 구 수치(224.4 토큰, 87.5% 절감)는 폐기하고 이 문서의 값으로 대체한다.
- **(추가, §10) 단일 호출 베이스라인과 비교하면 HarmoNet의 기제는 우위가 없다.** 오케스트레이션 없이 LLM 1회 호출(`single`)이
  244 토큰 / 95.0%로, HarmoNet v2(274 / 92.5%)와 v1(281 / 92.5%)보다 토큰은 적고 정확도는 같거나 높다.
  LangGraph 대비 우위는 "호출 횟수 감소"로 전부 설명되며, 이 설정에서 HarmoNet 고유 기제의 기여는 측정되지 않는다.

---

## 1. 측정 환경

| 항목 | 값 |
|---|---|
| 모델 | `qwen2.5-coder:7b` (Ollama, 로컬) — 5개 시스템 전부 동일 |
| 엔드포인트 | `http://localhost:11434/v1` (OpenAI 호환) — 5개 시스템 전부 동일 |
| 생성 파라미터 | temperature 0.2, max_tokens 1024 — 5개 시스템 전부 동일 |
| 토큰 집계 | 전 시스템 API 응답의 `usage` 필드 (Ollama 토크나이저 실측). `token_source=measured` 1,080/1,080행 |
| 과제 | HumanEval 20 + MBPP(sanitized) 20 = 40문제, 3회 반복 |
| 조건 | (A) eval-repair 포함: 5시스템 × 120행 (B) eval-repair 제외 `G1_DISABLE_EVAL_REPAIR=1`: 4시스템 × 120행 |
| 실측 증빙 | `verify_usage_output.txt` — `measured=True`, prompt 32 / completion 2 (시스템 프롬프트 포함 확인) |
| 브랜치 | `fair-measurement` (패치 0001, 0002 + 베이스라인 어댑터 수정) |

RunYourAI를 쓸 수 없어 상용 모델 대신 로컬 7B로 돌렸다. 따라서 **절대값은 구 측정(claude-haiku-4-5)과 비교 불가**하고,
시스템 간 **비율**만 의미가 있다. 논문용 최종 수치는 BACKEND.md 2단계(상용 API)로 다시 뽑는 것을 권장한다.

---

## 2. 구 측정이 왜 비교 불가였는가

RERUN.md의 배경 표에 이번 실측으로 드러난 사실을 반영해 정정한다.

| 시스템 | 구 집계 방식 (RERUN.md 기재) | **실제** (이번 확인) | 신 집계 방식 |
|---|---|---|---|
| LangGraph | `usage_metadata` API 실측 | 실측 맞음 | `ChatOpenAI` `usage_metadata` (API) |
| CrewAI | `usage_metrics` API 실측 | **추정이었음.** 커스텀 `BaseLLM`은 `crew.usage_metrics`를 채우지 않아 `_count_tokens(prompt)*3 + _count_tokens(output)` 폴백이 쓰였다. 증거: 구 CSV의 CrewAI `prompt_tokens` 120행 전부 3의 배수이고, 같은 문제의 3회 반복 값이 40/40 완전 동일 | `METER` (클라이언트가 `response.usage`에서 기록) |
| AutoGen | 단어수 추정 | 추정 맞음 | `OpenAIChatCompletionClient.total_usage()` (API) |
| HarmoNet v1 | 단어수×2 + 통신 0 선언 | 추정 맞음 | `METER` (API) |
| HarmoNet v2 | 단어수×1.3, 시스템 프롬프트 미포함 | 추정 맞음 | `METER` 델타 (API, 시스템 프롬프트 포함) |

즉 구 표에서 실측은 LangGraph 하나뿐이었다. "CrewAI 대비 24% 우위(295 vs 224)"는 추정 대 추정 비교였고,
양쪽 다 실측하면 격차는 훨씬 커진다.

---

## 3. 결과

### 3-A. 수리 경로 포함 (`g1_fair_20x3.csv`)

| system | n | pass rate | avg prompt | avg completion | avg total | sd | vs LangGraph | LLM calls/run | token_source |
|---|---|---|---|---|---|---|---|---|---|
| harmonet (v1) | 120 | 92.5% | 197 | 84 | 281 | 75 | 78.0% less | 1.00 | measured |
| harmonet_v2 | 120 | 92.5% | 204 | 109 | 313 | 196 | 75.5% less | 1.13 | measured |
| langraph | 120 | 93.3% | 696 | 583 | 1278 | 337 | (base) | 3.00 | measured |
| autogen | 120 | 94.2% | 621 | 230 | 852 | 295 | 33.4% less | 3.00 | measured |
| crewai | 120 | 95.0% | 778 | 217 | 995 | 282 | 22.1% less | 3.00 | measured |

| system | HumanEval pass | HumanEval tokens | MBPP pass | MBPP tokens |
|---|---|---|---|---|
| harmonet (v1) | 90.0% | 331 | 95.0% | 230 |
| harmonet_v2 | 95.0% | 328 | 90.0% | 299 |
| langraph | 93.3% | 1369 | 93.3% | 1187 |
| autogen | 95.0% | 1032 | 93.3% | 671 |
| crewai | 95.0% | 1154 | 95.0% | 837 |

### 3-B. 수리 경로 제외 (`g1_fair_norepair_20x3.csv`, `G1_DISABLE_EVAL_REPAIR=1`)

| system | n | pass rate | avg prompt | avg completion | avg total | sd | vs LangGraph | token_source |
|---|---|---|---|---|---|---|---|---|
| harmonet_v2 | 120 | 92.5% | 171 | 103 | 274 | 95 | 78.5% less | measured |
| langraph | 120 | 91.7% | 696 | 581 | 1277 | 356 | (base) | measured |
| autogen | 120 | 94.2% | 621 | 231 | 852 | 301 | 33.3% less | measured |
| crewai | 120 | 95.0% | 772 | 208 | 980 | 251 | 23.2% less | measured |

### 3-C. 구 → 신 변화 (`compare_runs.py` 출력, 수리 포함 기준)

```
system             구_토큰     신_토큰       변화     구_정확     신_정확  출처
autogen           814.5    851.7      +5%   100.0%    94.2%  measured
crewai            295.0    995.3    +237%    99.2%    95.0%  measured
harmonet_v2       224.4    313.2     +40%   100.0%    92.5%  measured
langraph         1790.6   1278.2     -29%    95.8%    93.3%  measured
```

모델이 다르므로(haiku → qwen 7B) 절대 변화율 자체는 해석하지 않는다. 읽어야 할 것은
**추정→실측으로 바뀐 시스템(CrewAI +237%, HarmoNet v2 +40%)에서 값이 오른 방향**이다.
LangGraph는 원래 실측이었고 모델만 바뀌어 -29%가 됐다.

---

## 4. 우위가 유지되는가 — 시스템별

| 비교 대상 | 구 주장 | 신 측정 (수리 포함) | 판정 |
|---|---|---|---|
| vs LangGraph | 87.5% 절감 | **75.5% 절감** (78.5%, 수리 제외) | 유지. 수치는 낮춰서 인용 |
| vs CrewAI | 24% 절감 (295 vs 224) | **68.5% 절감** (995 vs 313) | 유지·확대. 단, 구 수치가 추정 대 추정이었음을 명시 |
| vs AutoGen | 72% 절감 (814 vs 224) | **63.2% 절감** (852 vs 313) | 유지 |
| 정확도 | HarmoNet v2 100% | 92.5% (전 시스템 91.7~95.0%) | 동률. 우위 주장 불가 |

정확도 신뢰구간: n=120, p≈0.93 → 95% CI 반폭 ≈ ±4.6pp. 어떤 시스템 쌍도 유의한 차이가 없다.

---

## 5. 수리 포함 / 제외 조건 차이

- `repair_after_eval`는 HarmoNet v2에만 있어, 포함 조건에서는 v2만 "테스트 실패 → 2차 시도"를 받는다.
- 120행 중 10행에서 eval-repair가 발동했고 **그중 1행만 통과로 바뀌었다.** 정확도는 두 조건 모두 92.5%로 같다.
  두 조건은 별도 실행(샘플링 다름)이며, 실패 과제 집합도 거의 동일하다
  (포함: HumanEval/10 ×3, mbpp_2 ×2, mbpp_7, mbpp_20 ×2, mbpp_61 / 제외: HumanEval/10 ×3, mbpp_2 ×2, mbpp_7, mbpp_20 ×3).
- 토큰: 발동한 10행은 632~1056 토큰으로 평균의 2~3배가 들었고, 그 결과 평균이 274 → 313으로 **+14%**, 표준편차가 95 → 196으로 두 배가 됐다.
- **결론: 7B 모델에서 eval-repair는 비용만 늘리고 정확도를 거의 못 올렸다.** 논문 본표는 수리 제외(3-B) 값을 쓰고
  수리 포함은 보조 표로 두는 것이 대칭 조건 면에서 안전하다.

---

## 6. AutoGen 추정치 여부

**아니다. 이번에는 실측이다.** `OpenAIChatCompletionClient.total_usage()`가 API `usage`를 누적하므로
120/120행 `measured`. 구 측정의 AutoGen(814.5)이 단어수 추정이었음에도 신 실측(851.7)과 5% 차이인 것은
추정식이 우연히 근접했던 것이지 실측이었다는 뜻은 아니다.

---

## 7. 해석 시 주의할 점 (논문에 같이 써야 하는 것)

1. **호출 횟수가 격차의 본체.** 베이스라인은 3회 고정, HarmoNet v2는 평균 1.13회(builder 1회, 정적 검증 실패 시 6/120에서 repair 1회 추가).
   토큰 절감의 상당 부분은 "필요할 때만 다음 단계로 간다"는 설계에서 온다. 호출당 토큰은 v2 277 vs LangGraph 426으로 격차가 훨씬 작다.
2. **HarmoNet v1은 사실상 단일 프롬프트 베이스라인.** 2틱 씨앗 파이프라인이 이번 실행에서 LLM 호출을 0회 내고
   키워드 미달로 `repair_used=True`(120/120)가 되어, 유일한 LLM 호출이 repair 프롬프트였다. v1의 281 토큰은
   "직접 호출 1회"의 비용이지 협업 프로토콜의 비용이 아니다. 논문에서 v1 수치를 쓸 경우 이 사실을 병기해야 한다.
3. **모델이 작다.** 7B의 절대 토큰·정확도는 상용 모델과 다르다. 비율만 인용한다.
4. **전 시스템 공통 실패.** HumanEval/10(중첩 괄호 접두사)과 mbpp_20은 5개 시스템 모두 3/3 실패 → 모델 한계이지 오케스트레이션 차이가 아니다.
5. **지연시간**은 로컬 GPU 상태에 좌우되므로 비교 근거로 쓰지 않는다 (참고: v2 1.35s, LangGraph 6.55s — 호출 횟수에 비례).

---

## 8. 이번에 바꾼 것 (코드)

| 파일 | 변경 | 이유 |
|---|---|---|
| `harmonet/usage.py` (신규) | 스레드 안전 `UsageMeter` | 패치 0001 |
| `harmonet/llm.py` | 6개 호출 지점 `METER.record_from_response`; `openai_compatible` 백엔드; Ollama 네이티브 `prompt_eval_count` 기록 | 패치 0001, 0002 |
| `benchmark/agents_harmonet.py`, `agents_harmonet_v2.py` | 추정식 제거, `METER` 사용, `token_source` 보고 | 패치 0001 |
| `benchmark/external_g1.py` | `token_source` 컬럼, `G1_DISABLE_EVAL_REPAIR` | 패치 0001 |
| `benchmark/agents_langraph.py` | `openai_compatible` 분기 추가 (`ChatOpenAI(base_url=…)`), `token_source` (mock/wrapped는 estimated) | 기존엔 `langchain_openai` 미설치 시 **조용히 MockLLM으로 떨어졌다** |
| `benchmark/agents_crewai.py` | `OPENAI_COMPAT_*` 읽기, 토큰을 `METER`에서 | 커스텀 `BaseLLM`이 `usage_metrics`를 안 채움 → 구 값이 추정이었음 |
| `benchmark/agents_autogen.py` | `OPENAI_COMPAT_*` 읽기, 토큰을 `total_usage()`에서 | 단어수 추정 제거 |

세 어댑터 모두 Ollama로 돌릴 수 있었으므로 **비교에서 제외한 시스템은 없다.**
추가 설치: `pip install langchain-openai`.

---

## 9. 재현

```powershell
ollama pull qwen2.5-coder:7b
git checkout fair-measurement
python -X utf8 verify_usage.py          # measured=True 확인 (환경변수는 run_fair.ps1 참고)
powershell -File evidence\g1_fair\run_fair.ps1   # Task 5 + Task 6, 약 1.5시간 (RTX 로컬 기준)
python compare_runs.py evidence\g1\g1_v2_final_4way_20x3.csv g1_fair_20x3.csv
```

파일: `g1_fair_20x3.{json,csv,_report.txt}`, `g1_fair_norepair_20x3.{json,csv,_report.txt}`,
`g1_fair_pilot_5x1.{json,csv}` (5×1 예비 실행), `verify_usage_output.txt`, `compare_{repair,norepair}.txt`, `tables_{repair,norepair}.md`.

---

## 10. 어블레이션 — 단일 호출 베이스라인 vs HarmoNet (2026-09-11 추가)

**핵심 질문: HarmoNet의 기제(공명 게이팅, 저비용 검증, 지연 에스컬레이션)가 "그냥 한 번 호출하기"보다 나은가?**

§7-1에서 토큰 격차가 호출 횟수(1.1 vs 3)로 설명된다는 점이 드러났으므로, 대조군으로 오케스트레이션이 전혀 없는
`SingleCallAdapter`(`benchmark/agents_single.py`, 패치 0003)를 같은 조건으로 돌렸다. 시스템 프롬프트 1개 + 과제 프롬프트, LLM 정확히 1회 호출, 검증·수리·에스컬레이션 없음.

조건: Task 6과 동일 (`G1_DISABLE_EVAL_REPAIR=1`, humaneval+mbpp 20문제 × 3회, qwen2.5-coder:7b, temp 0.2, max_tokens 1024).
HarmoNet v2는 Task 6 데이터, HarmoNet v1은 Task 5 데이터(v1에는 `repair_after_eval`가 없어 두 조건이 동일).

### 10-A. 결과

| system | n | pass rate (95% CI) | avg prompt | avg completion | avg total | sd | tokens/call | calls/run | token_source |
|---|---|---|---|---|---|---|---|---|---|
| **single** | 120 | **95.0%** (±3.9) | 161 | 83 | **244** | 74 | 244 | 1.00 | measured |
| harmonet (v1) | 120 | 92.5% (±4.7) | 197 | 84 | 281 | 75 | 281 | 1.00 | measured |
| harmonet_v2 | 120 | 92.5% (±4.7) | 171 | 103 | 274 | 95 | 261 | 1.05 | measured |

| system | HumanEval pass | HumanEval tokens | MBPP pass | MBPP tokens | latency avg |
|---|---|---|---|---|---|
| single | 95.0% | 292 | 95.0% | 196 | 1.04s |
| harmonet (v1) | 90.0% | 331 | 95.0% | 230 | 1.97s |
| harmonet_v2 | 95.0% | 300 | 90.0% | 248 | 1.24s |

### 10-B. 과제별 짝 비교 (같은 40문제, 3회 통과 수 기준)

| 비교 | HarmoNet이 나은 과제 | 같음 | HarmoNet이 나쁜 과제 |
|---|---|---|---|
| harmonet_v2 vs single | **0** | 38 | 2 (mbpp_2, mbpp_7) |
| harmonet (v1) vs single | **0** | 39 | 1 (HumanEval/8) |

- `single`이 틀린 과제는 HumanEval/10, mbpp_20 — 5개 시스템 전부 틀리는 모델 한계 과제(§7-4)뿐이다.
- HarmoNet v2는 여기에 mbpp_2(2/3 실패), mbpp_7(1/3 실패)을 더 틀렸다. v1은 HumanEval/8(3/3 실패)을 더 틀렸다.
- 토큰: v2가 `single`보다 많이 쓴 과제 24/40, 과제별 중앙값 비율 v2/single = 1.03.

### 10-C. v2 에스컬레이션이 실제로 한 일

| v2 행 구분 | n | pass | avg tokens |
|---|---|---|---|
| builder 1회로 끝남 | 114 | 94.7% | 260 |
| 정적 검증 실패 → repair 호출 (mbpp_2 ×3, mbpp_7 ×3) | 6 | 50.0% | 544 |

에스컬레이션이 발동한 두 과제(mbpp_2, mbpp_7)는 **`single`이 3/3 통과한 과제**다. 즉 v2의 저비용 검증이 잡아낸 것은
v2 자신의 builder 프롬프트가 만든 실패이고, repair는 그중 절반만 되돌리면서 토큰을 2배 썼다.
builder 1회로 끝난 114행만 보아도 94.7% / 260 토큰으로 `single`(95.0% / 244)을 넘지 못한다.

### 10-D. 판정

**HarmoNet ≤ single.** 이 설정에서 HarmoNet의 기제는 "한 번 호출하기"보다 낫지 않다.

- 토큰: v2가 12% 많고(274 vs 244), v1은 15% 많다(281 vs 244). 차이의 대부분은 프롬프트(171·197 vs 161) — HarmoNet의 시스템 프롬프트·씨앗 헤더가 더 길다.
- 정확도: 2.5pp 낮고 CI 안이지만, 짝 비교에서 HarmoNet이 이긴 과제가 0개다. "동률"이 아니라 "같거나 나쁨"으로 읽는 것이 정확하다.
- 따라서 §4의 "LangGraph 대비 75.5% 절감"은 **HarmoNet의 기여가 아니라 3회 호출 대신 1회 호출한 결과**다.
  같은 절감은 `single`이 더 크게(80.9%) 달성한다.

이 결론이 뒤집힐 수 있는 조건은 두 가지뿐이고, 둘 다 이번 데이터로는 검증되지 않았다:
1. 7B가 아닌 더 약한/더 강한 모델에서 검증-에스컬레이션이 실제 실패를 구제하는 경우 (7B에서는 6회 중 3회, 그것도 자기 유발 실패).
2. HumanEval/MBPP처럼 단일 함수 과제가 아닌, 다단계 협업이 필요한 과제.

논문에서 HarmoNet의 기여를 주장하려면 이 `single` 행을 반드시 같은 표에 넣어야 하고, 현재 수치로는 "그래프 오케스트레이션 대비 절감"을
"단일 호출로 충분한 과제에서 3단계 파이프라인이 낭비"라는 일반적 관찰 이상으로 해석할 수 없다.

파일: `g1_fair_single_norepair_20x3.{json,csv,_report.txt}`, 실행 스크립트 `run_single.ps1`.
