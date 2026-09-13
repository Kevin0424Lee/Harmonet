# G1 재측정 — 전 시스템 동일 기준 토큰 비교 (2026-09-11, 2026-09-12 정정)

> **2026-09-12 정정 요약 (AUDIT.md 반영).** 이 문서의 9월 11일자 수치 중 다음은 독립 감사로 오류가 확인돼 정정됐다.
> 상세: `AUDIT.md` §2·§3, 재실행 산출물 `rerun/README.md`, `../swe_fair/haiku_0_30_4k_nohints/README.md`.
>
> 1. **N1 — HarmoNet v1은 9월 실행 전체에서 난수 임베딩 위에서 돌았다.** `huggingface-hub` 버전 충돌로 sentence-transformers 로드가 실패했고 `embed.py`가 조용히 MD5 시드 난수 벡터로 폴백했다. 공명 게이트는 한 번도 열리지 않았다(v1 120/120행 `seeds_received=0`). 따라서 "공명 게이팅의 기여 없음"이 아니라 **"공명 게이팅은 실행된 적 없음, 미측정"**이다. 복구 후 재실행: v1 95.0% / 434 토큰, `seeds_received=2` ×120 (§10-E).
> 2. **N2 — v2의 짝 비교 2패(mbpp_2, mbpp_7)는 하네스 버그.** `external_g1.py`의 진입점 정규식이 `assert set(f(...))`에서 `set`을 잡아 프롬프트가 "define function `set`"이 됐고, v2 정적 검증만 이를 강제해 repair를 유발했다. 수정 후 재실행: v2 vs single **1승 39무 0패** (§10-E). "HarmoNet ≤ single(같거나 나쁨)"은 철회하고 **"구별되지 않음"**으로 고친다.
> 3. **N4 — "노이즈 ±2/30 동일 조건 반복 실측"은 사실이 아니었다.** 세 조건 간 교차 관찰의 사후 추정이었다. 동일 조건 반복은 2026-09-12에 처음 실행했고 결과는 ±1/30 (§11-F).
> 4. **N3 — 구 체인 "18→43→50"은 인용 불가.** 43→50 "시맨틱 수리"는 공식 하네스의 `FAIL_TO_PASS` 히든 테스트 결과를 프롬프트에 넣는 test-set leakage였다(`swebench_semantic_repair.py:84-119`). 43 이하도 oracle 파일 + hints 조건이다.
> 5. **N5·N6 — SWE-bench 수치 전부에 "(oracle 파일 제공)" 단서.** 9월 11일 실행은 추가로 `hints_text` 포함·`max_tokens=1024`였다. 09-12 재실행은 hints 제거·4096 (§11-F).
> 6. **N7 — 표 1 LangGraph 정확도 93.3%는 repair 실행 값.** norepair는 91.7%. §4 표 정정.
> 7. **N8 — 정확도 CI는 n=120이 아니라 과제 단위 n=40으로.** 실패가 과제 단위로 완전 군집한다. §10-E에 과제 단위 부트스트랩 CI.
> 8. **validator는 실제 검증을 수행하지 않는다.** `agent.py:155` `decode_seed`가 `rule_description`만 반환해 builder 출력이 validator에 전달되지 않으며, validator는 자기 출력과 무관하게 "passed" 씨앗을 만든다(`:759-772`). G1의 "LLM 검증 기여 없음"은 **"validator가 실제 검증을 수행하지 않음"**으로 읽어야 한다.
> 9. **G3 "Redis 장애 복구 PASS"는 무효.** 컨테이너는 health 서버만 실행하고 store는 기동되지 않았으며, store가 읽는 `HARMONET_REDIS_HOST`(기본 127.0.0.1)와 Compose의 `REDIS_HOST=redis`가 달라 연결될 수도 없었다. `/readyz`는 `ready=True` 하드코딩이라 Redis 유무와 무관하게 200이다.
>
> **채점기 교체 (2026-09-13, Week1-A7c).** 이 문서의 모든 HumanEval/MBPP 통과율은 **옛 채점기**로 나왔다: 후보+테스트를 한 파일로 실행하고
> **종료 코드 0 = 통과**로 판정했으며 **후보 코드를 저장하지 않았다**. 종료 코드는 `sys.exit(0)` 등으로 위조 가능하다(`tests/test_verify_adversarial.py`).
> 새 채점기(`verify.score_hidden`: 하네스가 테스트를 개별 실행하고 nonce 가 든 result.json 으로만 판정, 후보 코드·추출 방식을 CSV 에 저장)로
> 7B norepair 20×3 을 재실행하고 **같은 후보 360개**를 두 채점기에 넣어 대조한 결과, **거짓 통과 0건**(single 114/114, v2 114/114, v1 112/112),
> 옛 CSV 와의 과제별 차이는 single 0/40, v2 1/40, v1 2/40 과제로 40문제 규모에서 구분되지 않는다(별도 실행이라 원인 귀속 불가).
> 즉 취약점은 실재했지만 **이번에 저장한 후보 360개에 한해** 발동하지 않았다 — 후보를 저장하지 않은 과거 실행에는 소급 적용할 수 없다.
> 이 문서의 수치는 그 전제 아래 유지된다. 상세: `RESCORE.md`. 단, MBPP 는 채점 테스트가 프롬프트에 노출돼 있어(`hidden_exposed`) 히든 점수가 아니다.
>
> 아래 본문에서 정정된 문장은 ~~취소선~~ 뒤에 정정문을 붙였다.

## 결론 먼저

- **LangGraph 대비 우위는 유지된다.** 같은 모델·같은 엔드포인트·같은 집계 기준(API `usage`)으로
  HarmoNet v2는 LangGraph보다 토큰을 **75.5% 적게** 쓴다 (수리 포함 313 vs 1278). 수리 제외 조건에서는 78.5%.
- **CrewAI 대비 우위는 뒤집히지 않았다 — 하지만 예상과 다른 이유다.** 구 측정의 CrewAI 값(295)은
  "API 실측"이 아니라 단어수 추정이었음이 이번에 확인됐다(아래 §2). 실측하면 CrewAI는 995로, HarmoNet v2(313)의 약 3.2배다.
- **정확도는 5개 시스템이 92.5~95.0%로 구분되지 않는다.** 차이(±2.5pp)는 95% 신뢰구간(±4~5pp) 안이다.
  7B 모델에서도 변별력은 거의 나오지 않았다 — 전 시스템이 공통으로 틀리는 문제(HumanEval/10, mbpp_20)가 실패의 대부분이다.
- **토큰 격차의 주된 원인은 호출 횟수다.** 베이스라인 3개는 고정 3회 호출(architect→builder→validator),
  HarmoNet v2는 평균 1.13회(builder 1회 + 정적 검증 실패 시에만 escalation). 논문에서는 이 점을 함께 서술해야 한다.
- 구 수치(224.4 토큰, 87.5% 절감)는 폐기하고 이 문서의 값으로 대체한다.
- **(추가, §10; 09-12 정정) 단일 호출 베이스라인과 HarmoNet v2는 구별되지 않는다.** ~~오케스트레이션 없이 LLM 1회 호출(`single`)이
  244 토큰 / 95.0%로, HarmoNet v2(274 / 92.5%)와 v1(281 / 92.5%)보다 토큰은 적고 정확도는 같거나 높다.~~
  진입점 버그 수정 후: single 244.9 / 95.0%, v2 254.6 / 95.8%, 짝 비교 1승 39무 0패 (§10-E).
  LangGraph 대비 우위는 "호출 횟수 감소"로 전부 설명된다. **공명 게이팅은 9월 11일 실행에서 실행된 적이 없어(N1) 기여가 측정되지 않았다**;
  복구 후 v1은 95.0% / 434 토큰으로 single과 정확도 동일, 토큰 1.8배다.

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

### 1-A. Ollama 컨텍스트 절단 검증 (2026-09-11 추가)

Ollama는 프롬프트가 컨텍스트 창을 넘으면 앞부분을 잘라 버리고 `prompt_eval_count`에는 잘린 뒤의 수만 남긴다.
G1 실행이 잘린 채 채점됐는지 서버 로그(`%LOCALAPPDATA%\Ollama\server.log`)로 확인했다.

- 이 환경의 실제 창: `n_ctx_slot = 4096`, `OLLAMA_NUM_PARALLEL=1`.
- Ollama는 절단 시 `level=WARN msg="truncating input prompt"`를 남긴다. 전체 로그에서 이 경고는 **2건**뿐이며,
  둘 다 21:58:51~54의 의도적 13k 토큰 프로브 호출(G1 종료 후, 32k 모델 생성 전)이다.
- 러너가 본 프롬프트 길이(`task.n_tokens`) 2,857건 중 G1 구간(18:04~21:44 모델 로드)에 1,024 토큰 이상인 요청은 **0건**.
  1,024 이상인 요청은 전부 21:58 이후(프로브 2건 + SWE-bench 파일럿, 32k 모델)이다.
- CSV 교차 확인: 행별 `prompt_tokens`(3회 호출 합) 최대는 CrewAI 1,322, LangGraph 1,110 — 단일 호출은 그보다 작다. 2,048 근처 군집 없음.

**판정: G1 재측정(§3, §10)은 절단 없이 채점됐다. 결과 유효.**
SWE-bench처럼 긴 프롬프트가 필요한 실험은 `qwen2.5-coder:7b-32k`(num_ctx 32768) 파생 모델을 쓴다.

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

> **(09-12)** 이 표의 v1 행은 난수 임베딩 상태(N1), v2 행은 진입점 버그(N2)의 영향을 받았다. 인용 가능한 HarmoNet 수치는 §10-E. 베이스라인 3행은 유효.

| system | n | pass rate | avg prompt | avg completion | avg total | sd | vs LangGraph | LLM calls/run | token_source |
|---|---|---|---|---|---|---|---|---|---|
| harmonet (v1) — **N1 오염** | 120 | 92.5% | 197 | 84 | 281 | 75 | 78.0% less | 1.00 | measured |
| harmonet_v2 — **N2 오염** | 120 | 92.5% | 204 | 109 | 313 | 196 | 75.5% less | 1.13 | measured |
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
| 정확도 | HarmoNet v2 100% | 92.5% (전 시스템 91.7~95.0%; LangGraph는 norepair 91.7%, repair 93.3% — 두 실행을 섞지 말 것) | 구분되지 않음. 우위 주장 불가 |

~~정확도 신뢰구간: n=120, p≈0.93 → 95% CI 반폭 ≈ ±4.6pp.~~ **(09-12 정정, N8)** 120행은 40과제 × 3반복이고 실패가 과제 단위로 완전 군집하므로(HumanEval/10, mbpp_20은 전 시스템 3/3 실패) 유효 n은 40이다. 과제 단위 부트스트랩 95% CI는 ±7pp 이상(§10-E: single 87.5–100, v2 89.2–100). 어떤 시스템 쌍도 유의한 차이가 없다는 결론은 그대로다.

---

## 5. 수리 포함 / 제외 조건 차이

- `repair_after_eval`는 HarmoNet v2에만 있어, 포함 조건에서는 v2만 "테스트 실패 → 2차 시도"를 받는다.
- 120행 중 10행에서 eval-repair가 발동했고 **그중 1행만 통과로 바뀌었다.** 정확도는 두 조건 모두 92.5%로 같다. **(09-12)** 발동 10행 중 mbpp_2 ×2, mbpp_7 ×1은 진입점 버그(N2)가 만든 실패이므로 이 수치도 오염돼 있다. 또한 이 eval-repair는 실제 테스트를 실행해 실패 메시지를 주는 "현실에 묻는 검증"인데 7B·포화 과제에서 10회 중 1회 구제에 그쳤다 — "LLM에게 묻는 검증은 효과 없고 현실에 묻는 검증은 효과 있다"는 가설에 대한 G1 쪽 반례다(모델·과제가 SWE-bench와 달라 통제 비교는 아님).
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
2. **HarmoNet v1은 (09-11 실행에서) 사실상 단일 프롬프트 베이스라인이었다 — 원인은 임베딩 폴백(N1).** 2틱 씨앗 파이프라인이 LLM 호출을 0회 내고
   키워드 미달로 `repair_used=True`(120/120)가 된 이유는 sentence-transformers 로드 실패로 `embed.py`가 난수 벡터로 폴백해
   공명 게이트(cos ≥ 0.15)가 결정론적으로 열리지 않았기 때문이다. v1의 281 토큰은 "직접 호출 1회"의 비용이지 협업 프로토콜의 비용이 아니다.
   **09-12 복구 후 재실행에서는 120/120행 `seeds_received=2, tasks_completed=2`, `repair_used` 3/120으로 게이트가 열렸고, 95.0% / 434 토큰이다(§10-E).**
   09-11 v1 수치(281 / 92.5%)는 HarmoNet 기제의 수치로 인용하지 않는다.
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

> **(09-12)** 아래 09-11 표는 기록용. CI(±3.9/±4.7)는 n=120 이항 CI로 과소(N8) — 과제 단위 CI는 §10-E. v1·v2 행은 N1·N2 오염.

| system | n | pass rate (95% CI, n=120 이항 — 과소) | avg prompt | avg completion | avg total | sd | tokens/call | calls/run | token_source |
|---|---|---|---|---|---|---|---|---|---|
| **single** | 120 | **95.0%** (±3.9) | 161 | 83 | **244** | 74 | 244 | 1.00 | measured |
| harmonet (v1) — N1 오염 | 120 | 92.5% (±4.7) | 197 | 84 | 281 | 75 | 281 | 1.00 | measured |
| harmonet_v2 — N2 오염 | 120 | 92.5% (±4.7) | 171 | 103 | 274 | 95 | 261 | 1.05 | measured |

| system | HumanEval pass | HumanEval tokens | MBPP pass | MBPP tokens | latency avg |
|---|---|---|---|---|---|
| single | 95.0% | 292 | 95.0% | 196 | 1.04s |
| harmonet (v1) | 90.0% | 331 | 95.0% | 230 | 1.97s |
| harmonet_v2 | 95.0% | 300 | 90.0% | 248 | 1.24s |

### 10-B. 과제별 짝 비교 (같은 40문제, 3회 통과 수 기준)

> **(09-12 정정, N2)** 아래 표의 v2 "나쁜 과제 2"는 하네스 진입점 버그의 산물이다. 수정 후 결과는 §10-E. 이 표는 09-11 실행의 기록으로만 남긴다.

| 비교 | HarmoNet이 나은 과제 | 같음 | HarmoNet이 나쁜 과제 |
|---|---|---|---|
| harmonet_v2 vs single (09-11, 버그 상태) | 0 | 38 | ~~2 (mbpp_2, mbpp_7)~~ → 하네스 버그 |
| harmonet (v1) vs single (09-11, 난수 임베딩) | 0 | 39 | 1 (HumanEval/8) — 인용 불가(N1) |
| **harmonet_v2 vs single (09-12, 수정 후)** | **1** (mbpp_20: 1/3 vs 0/3) | **39** | **0** |
| **harmonet v1 vs single (09-12, 임베딩 복구)** | **0** | **40** | **0** |

- `single`이 틀린 과제는 HumanEval/10, mbpp_20 — 5개 시스템 전부 틀리는 모델 한계 과제(§7-4)뿐이다.
- ~~HarmoNet v2는 여기에 mbpp_2(2/3 실패), mbpp_7(1/3 실패)을 더 틀렸다.~~ mbpp_2·mbpp_7 실패는 프롬프트가 "define function `set`"을 요구한 하네스 버그였고, 수정 후 v2는 두 과제 모두 3/3 통과다.
- 토큰(09-11): v2가 `single`보다 많이 쓴 과제 24/40, 과제별 중앙값 비율 v2/single = 1.03.

### 10-C. v2 에스컬레이션이 실제로 한 일

| v2 행 구분 | n | pass | avg tokens |
|---|---|---|---|
| builder 1회로 끝남 | 114 | 94.7% | 260 |
| 정적 검증 실패 → repair 호출 (mbpp_2 ×3, mbpp_7 ×3) | 6 | 50.0% | 544 |

~~에스컬레이션이 발동한 두 과제(mbpp_2, mbpp_7)는 **`single`이 3/3 통과한 과제**다. 즉 v2의 저비용 검증이 잡아낸 것은
v2 자신의 builder 프롬프트가 만든 실패이고, repair는 그중 절반만 되돌리면서 토큰을 2배 썼다.~~
**(09-12 정정, N2)** 에스컬레이션 6행은 전부 하네스가 `expected_keywords=["set"]`을 요구해 v2 정적 검증이 "missing function `set`"으로 실패한 것이다.
v2 builder 프롬프트의 문제가 아니라 진입점 추론 버그다. 수정 후 재실행에서는 **120/120행 calls=1, repair 발동 0회**다.
builder 1회로 끝난 114행(09-11)의 94.7% / 260 토큰은 `single`(95.0% / 244)과 구별되지 않는다.

### 10-D. 판정

~~**HarmoNet ≤ single.** 이 설정에서 HarmoNet의 기제는 "한 번 호출하기"보다 낫지 않다.~~

**(09-12 정정) HarmoNet v2 = single. 공명 게이팅(v1)은 09-11 실행에서 평가되지 않았고, 복구 후에는 정확도 동일·토큰 1.8배다.**

- 토큰: ~~v2가 12% 많고(274 vs 244), v1은 15% 많다(281 vs 244). 차이의 대부분은 프롬프트(171·197 vs 161) — HarmoNet의 시스템 프롬프트·씨앗 헤더가 더 길다.~~
  **(N9)** v2의 09-11 초과분은 프롬프트가 아니라 (i) completion 103 vs 83(출력이 더 김), (ii) 버그로 2회 호출한 6행이었다. v2 시스템 프롬프트(12단어)는 single(33단어)보다 짧고, builder 1회로 끝난 행의 prompt 평균 156.6은 single 161보다 작다. 수정 후 v2 254.6 vs single 244.9(+4%). v1(복구 후) 434는 두 씨앗 실행(builder+validator)의 비용이다.
- 정확도: ~~2.5pp 낮고 CI 안이지만, 짝 비교에서 HarmoNet이 이긴 과제가 0개다. "동률"이 아니라 "같거나 나쁨"으로 읽는 것이 정확하다.~~
  수정 후 v2 95.8% vs single 95.0%, 짝 비교 1승 39무 0패(차이 1건은 mbpp_20 1회 통과 — 40문제 규모에서 구분 불가). **"구별되지 않음"**이다.
- 따라서 §4의 "LangGraph 대비 75.5% 절감"은 **HarmoNet의 기여가 아니라 3회 호출 대신 1회 호출한 결과**다.
  같은 절감은 `single`이 더 크게(80.9%) 달성한다. (이 문장은 정정 후에도 유효.)

이 결론이 뒤집힐 수 있는 조건은 두 가지뿐이고, 둘 다 이번 데이터로는 검증되지 않았다:
1. 7B가 아닌 더 약한/더 강한 모델에서 검증-에스컬레이션이 실제 실패를 구제하는 경우 (7B에서는 6회 중 3회, 그것도 자기 유발 실패).
2. HumanEval/MBPP처럼 단일 함수 과제가 아닌, 다단계 협업이 필요한 과제.

논문에서 HarmoNet의 기여를 주장하려면 이 `single` 행을 반드시 같은 표에 넣어야 하고, 현재 수치로는 "그래프 오케스트레이션 대비 절감"을
"단일 호출로 충분한 과제에서 3단계 파이프라인이 낭비"라는 일반적 관찰 이상으로 해석할 수 없다.

파일: `g1_fair_single_norepair_20x3.{json,csv,_report.txt}`, 실행 스크립트 `run_single.ps1`.

### 10-E. 재실행 (2026-09-12) — 임베딩 복구(N1) + 진입점 수정(N2) 후

조건은 §10과 동일(norepair, qwen2.5-coder:7b, 40과제 × 3회). 상세: `rerun/README.md`.

| system | n | pass rate | 과제단위 95% CI (n=40, bootstrap) | avg prompt | avg completion | avg total | calls/run | 비고 |
|---|---|---|---|---|---|---|---|---|
| single | 120 | 95.0% | 87.5 – 100 | 161 | 84 | 244.9 | 1.00 | |
| harmonet_v2 | 120 | 95.8% | 89.2 – 100 | 158 | 96 | 254.6 | 1.00 | repair 0회 |
| harmonet (v1) | 120 | 95.0% | 87.5 – 100 | 284 | 150 | 433.8 | ≈2 | `seeds_received=2` ×120, `repair_used` 3/120 |

짝 비교(40과제, 3회 통과 수): v2 vs single **1 / 39 / 0**, v1 vs single **0 / 40 / 0**. 실패 과제는 HumanEval/10(전 시스템 0/3), mbpp_20(single 0/3, v2 1/3)뿐.

- v1의 두 번째 호출은 validator 씨앗 실행이지만, validator는 builder 출력을 받지 않는다(`agent.py:155`, `:759-772`). 따라서 434 토큰 중 절반은 **검증이 아닌 호출**의 비용이다.
- 이 표가 현재 G1에서 인용 가능한 유일한 HarmoNet 수치다. §3, §10-A의 v1·v2 행은 각각 N1·N2로 오염돼 있다.

---

## 11. SWE-bench Lite 어블레이션 — 수리 루프와 HarmoNet 구조의 기여 (2026-09-11 추가)

**핵심 질문: 어려운 과제에서 검증·수리가 "한 번 호출"을 이기는가?**

G1(§10)에서는 졌다. SWE-bench Lite에서 같은 대조군을 다시 놓았다. 상세 산출물: `evidence/swe_fair/haiku_0_30/`, 사전 등록: `evidence/swe_fair/README.md`.

### 11-A. 설계

| 조건 | 어댑터 | 러너 옵션 | 분리하는 것 |
|---|---|---|---|
| (a) single_novalidate | single | `--no-validate-patches` | LLM 1회, 검증·수리 없음 (대조군) |
| (b) single_validate | single | `--drop-invalid` (apply-check → 수리 프롬프트, 코드상 최대 4회: malformed 2 + hunk 1 + other 1) | (a)→(b) = **수리 루프의 기여** |
| (c) harmonet_validate | harmonet | `--drop-invalid` | ~~(b)→(c) = **HarmoNet 프롬프트/구조의 기여**~~ **(09-12) 난수 임베딩 상태로 실행됨 — 미측정(N1)** |

- 모델: `claude-haiku-4-5` (Anthropic API 직접, temperature 0.2, max_tokens 1024) — 세 조건 동일. **(09-12, N5)** 1024는 패치 과제에 낮은 상한이다. (a)에서 completion이 정확히 1024인 인스턴스 3개(astropy-7746, django-11564, django-11910) 중 2개가 (a)의 apply 오류 7건에 포함된다 — (a)의 실패 일부는 절단이 만들었다.
- 인스턴스: SWE-bench Lite test 0–29 (데이터셋 순서; astropy 6 + django 24). 세 조건 동일.
- 컨텍스트: 세 조건 모두 같은 oracle 파일 컨텍스트(`_make_prompt`, 36k chars 한도). **컨텍스트 검색은 이 실험의 변수가 아니다.**
  **(09-12, N6)** 프롬프트에는 `hints_text`(수정 PR 이전 이슈 코멘트, 종종 해법 포함)도 들어갔다. 표준 SWE-bench 시스템은 쓰지 않는다. 따라서 이 절의 모든 resolve 수는 **"oracle 파일 + hints 제공"** 조건의 값이며 리더보드 수치와 비교할 수 없다. within-run 비교(a↔b↔c)에는 영향 없다.
- **(09-12)** "(a) 검증·수리 없음"은 부정확하다. `_extract_patch→_clean_patch→_normalize_patch→_recount_hunks`의 기계적 형식 정규화는 세 조건 모두에 적용된다. (a)는 "apply-check 없음"이다. 수리 상한도 문서의 "최대 3회"가 아니라 코드상 malformed 2 + hunk 1 + other 1 = 최대 4회다.
- 채점: 공식 SWE-bench 하네스(swebench 5.0.2, Docker) — 실제 테스트 실행.
- 토큰: 전 조건 API `usage` 실측. 비용 총 $0.755.
- 해석 규칙과 1차 관찰 대상(수리 발동률)은 실행 전에 `evidence/swe_fair/README.md`에 고정했다.

### 11-B. 결과

모든 수치는 **oracle 파일 + hints 제공, max_tokens 1024** 조건 (09-11 실행). 재실행(hints 제거, 4096, 반복 2회)은 §11-F.

| 조건 | resolved | 95% CI | 첫 시도 apply 실패 | 수리로 복구 | 수리 후에도 실패 | 수리 호출 | 평균 토큰/인스턴스 | 비용 |
|---|---|---|---|---|---|---|---|---|
| (a) single_novalidate | **11/30** (37%) | ±17pp | 7 (미검증 제출 → 하네스 apply 오류; 그중 2건은 1024 절단) | — | — | 0 | 4,408 | $0.187 |
| (b) single_validate | **14/30** (47%) | ±18pp | 11 | 5 | 6 (drop) | 13 | 7,670 (+74%) | $0.311 |
| (c) harmonet_validate | **11/30** (37%) — **HarmoNet 조건 수치로 인용 불가(N1)** | ±17pp | 9 | 4 | 5 (drop) | 9 | 6,831 (+55%) | $0.257 |

**(09-12, N1)** (c)의 생성 로그 18행에 `SentenceTransformers 로드 실패 … 오프라인 결정론적 대체 모드` 경고가 있다. (c)는 공명 게이트가 죽은 상태에서 v1 어댑터의 키워드 repair 프롬프트("Repair this benchmark answer… Missing required terms: diff --git, <파일경로>") + 기본 시스템 프롬프트("You are a HarmoNet collaborative AI agent…")로 패치를 만든 것이다. HarmoNet 구조와 무관한 프롬프트 조합의 성적이므로 "(b)→(c) = HarmoNet 구조의 기여"는 이 데이터로 측정되지 않았다.

**1차 관찰 대상 — 수리 발동률: 0이 아니다.** (b)에서 30개 중 11개(37%)가 첫 시도에 `git apply`를 통과하지 못했고, 그중 5개가 수리로 복구됐다. 3개 비용 확인에서 0회였던 것은 표본이 작아서였다. 따라서 (a)와 (b)는 구조적으로 다른 실행이다.

### 11-C. 인스턴스별 짝 비교

| 비교 | 공통 resolved | 앞쪽만 | 뒤쪽만 |
|---|---|---|---|
| (a) vs (b) | 11 | — | django-11001 (+수리), django-11422 (+수리), django-11797 |
| (b) vs (c) | 11 | django-11422, django-11583, django-12113 | — |
| (a) vs (c) | 9 | django-11583, django-12113 | django-11001, django-11797 |

- (b)가 (a)보다 더 푼 3개 중 **2개(11001, 11422)는 수리로 복구된 패치**다 — (a)에서는 같은 인스턴스의 패치가 적용조차 안 됐다(하네스 apply 오류). 나머지 1개(11797)는 수리 없이 첫 시도에 통과 → 샘플링 노이즈.
- ~~노이즈 바닥: 수리도 drop도 없는 동일 조건 호출에서 결과가 뒤집힌 인스턴스가 2개 있다(astropy-14995는 (a)에서 첫 시도 해결, (b)(c)에서는 수리 필요; django-11797은 (a) 실패, (b)(c) 성공). **temperature 0.2에서도 30개 중 ±2개는 실행 간 노이즈**로 봐야 한다.~~
  **(09-12 정정, N4)** 위 ±2는 동일 조건 반복이 아니라 세 조건 간 교차 관찰의 사후 추정이었다. 동일 조건 반복은 09-12에 처음 실행했고 결과는 **±1/30** (§11-F). 09-11 문서 어디에도 "동일 조건 반복으로 실측"이라고 써서는 안 된다.
- (c)가 (b)보다 덜 푼 3개는 전부 (c)에서 패치가 첫 시도에 적용됐지만 테스트를 통과하지 못한 경우다. HarmoNet 프롬프트가 "적용은 되지만 틀린" 패치를 더 만들었거나, 노이즈다. 3개 차이는 노이즈 바닥(±2)과 구별되지 않는다.
- 세 조건 모두 drop된 인스턴스(10924, 11049, 11620, 11910, 11999)는 (a)에서도 하나도 못 풀었다 — 수리가 포기한 것은 어차피 못 푸는 것들이었다.

### 11-D. 판정 (사전 등록 규칙 적용)

| 규칙 | 관찰 | 판정 |
|---|---|---|
| (b)>(a) → 수리 루프의 기여 | +3 (37%→47%), 그중 2개가 수리로 복구된 패치. CI ±18pp 안 | **방향은 기여 쪽이나 통계적으로 구별되지 않음.** 기제 추적으로는 "적용 불가 패치 2/30을 살렸다"가 실측된 최소 기여 |
| (c)>(b) → HarmoNet 프롬프트/구조의 기여 | −3 (47%→37%) | ~~**기여 없음.**~~ **(09-12) 미측정.** (c)는 난수 임베딩 위에서 돌아 HarmoNet 구조가 실행되지 않았다(N1) |
| (c)<(a) → 기제가 해로움 | 0 (11 vs 11) | ~~**해롭지도 않음.**~~ **(09-12) 미측정.** 같은 이유 |
| (a)≈(b)≈(c) + 수리 0회 → 파이프라인 무의미 | 해당 없음 (수리 13회 발동, 5회 복구) | 이 규칙은 발동하지 않음 |

**결론.**
1. **apply-check 수리 루프는 실제로 일한다** — 첫 시도에 적용되지 않는 패치(11/30)의 절반가량을 살리고, 그중 일부가 실제로 테스트를 통과한다. 비용은 토큰 +74%. n=30에서 우위를 통계적으로 주장할 수는 없지만, G1(§10)과 달리 **기제가 무의미하다는 결과는 아니다.** 어려운 과제에서는 검증·수리가 값을 할 여지가 있다는 방향 신호다.
2. **그 기여는 HarmoNet 고유의 것이 아니다.** 수리 루프는 `swebench_g1.py`에 있고 어댑터와 무관하다. ~~`single` 어댑터에 같은 루프를 붙인 (b)가 HarmoNet 어댑터 (c)보다 같거나 낫다. HarmoNet 프롬프트/구조는 이 실험에서 측정 가능한 기여가 없다.~~ **(09-12)** (c)는 HarmoNet 구조가 실행되지 않은 실행이므로 "(b) ≥ (c)"에서 HarmoNet 구조에 관한 결론을 끌어낼 수 없다. **공명 게이팅의 SWE-bench 기여는 미측정**이다.
3. **논문 주장의 재배치:** "저비용 검증·표적 수리가 resolve율을 올린다"는 주장은 방향 신호로만 살릴 수 있으며(§11-F: +2~3/30, 노이즈 ±1, CI 안), 그 주어는 HarmoNet이 아니라 **프레임워크 무관한 apply-check 수리 루프**다. ~~HarmoNet의 에이전트 구조는 G1(단순 과제)에서도 SWE-bench(어려운 과제)에서도 단일 호출 대비 우위를 보이지 않았다.~~ **(09-12)** G1에서는 v2 = single(§10-E), v1(복구 후) = single 정확도·토큰 1.8배. SWE-bench에서는 미측정. **"세 시험 모두에서 기제 기여 없음"이라는 서술은 틀렸고, "공명 게이팅은 09-11까지 실행된 적 없음, 미측정"이 맞다.**

### 11-E. 한계

- **n=30.** 신뢰구간 ±17~18pp. 이 표에서 3개 차이는 "구별되지 않음"이다. 100개로 확대하면 CI ±10pp — 그래도 (a)–(b)의 10pp 차이를 확정하기엔 부족할 수 있다.
- **컨텍스트 검색을 테스트하지 않았다.** ~~과거 체인(18→17→43→50)에서 가장 큰 도약(17→43)은 컨텍스트 검색이었다.~~ **(09-12)** 구 체인의 17은 Windows 경로 버그로 패치 69개가 비었던 실행이므로 17→43 도약도 컨텍스트 검색 효과라고 볼 근거가 없다. "컨텍스트 검색"이라 불린 것도 실제로는 oracle 파일 제공(`swebench_g1.py:356`)이지 검색 기제가 아니다. 이 실험은 수리 쪽 개입만 분리했으므로, 결과를 "HarmoNet의 모든 기제가 무의미"로 일반화하면 안 된다. 다음 실험은 **(d) single + 컨텍스트 검색**이다.
- ~~**기존 18/43/50과의 비교는 하지 않는다.** 당시 파이프라인(옵션·프롬프트·컨텍스트 한도·RunYourAI 라우팅)이 지금과 동일함을 증명할 수 없다. 참고값으로만: 당시 "컨텍스트" 조건 100개 중 0–29 구간의 resolved는 별도 추출해 `evidence/swe_fair/README.md`에 기록한다.~~
  **(09-12 정정, N3) 구 체인 18→43→50은 참고값으로도 인용하지 않는다.** 43→50 "시맨틱 수리"(`benchmark/swebench_semantic_repair.py:84-119`)는 공식 하네스 `report.json`의 `FAIL_TO_PASS` 실패 테스트명과 `test_output.txt` 꼬리를 프롬프트에 넣는다 — 채점용 히든 테스트의 누출이며 리더보드 기준 실격 사유다. 43 이하도 oracle 파일 + hints 조건이고, "17 (에러 0, 빈 패치 69)"는 `swebench_g1.py:99-100`에 기록된 Windows 상대경로 버그와 정합한다. 피어리뷰 S1/S2, 재측정_프로토콜 §4, 교수보고서 부록 A의 "SWE-bench 증거는 유효"는 모두 철회.
- ~~**실행 간 노이즈 ±2/30**이 temperature 0.2에서도 존재한다. 반복 실행(repeats) 없이 단일 실행이다.~~ **(09-12)** 09-11 실행은 반복 없는 단일 실행이었고 ±2는 사후 추정이었다. 실측 노이즈는 §11-F.

### 11-F. 재실행 (2026-09-12) — max_tokens 4096, hints 제거, (a) 2회 반복

산출물: `evidence/swe_fair/haiku_0_30_4k_nohints/`. 인스턴스·모델·oracle 파일 컨텍스트·하네스는 §11-A와 동일. **oracle 파일 제공 조건은 그대로**이므로 절대값은 여전히 표준과 비교 불가. (c)는 재실행하지 않았다.

| 조건 | resolved | 하네스 apply 오류 | drop | 수리 호출 | 평균 토큰/인스턴스 | 비용 |
|---|---|---|---|---|---|---|
| (a) single_novalidate, 1회차 | **8/30** | 7 | — | 0 | 4,177 | $0.227 |
| (a) single_novalidate, 2회차 | **9/30** | 9 | — | 0 | 4,216 | $0.233 |
| (b) single_validate | **11/30** | 0 | 8 | 17 | 7,846 (+87%) | $0.367 |

- **노이즈 바닥(실측):** (a) 1회차 vs 2회차 — 공통 resolved 8, 뒤집힌 인스턴스 1개(django-11964). resolve 수 기준 **±1/30**. 단, 첫 시도 apply 오류 집합은 7개 vs 9개로 5개만 겹친다 — "적용 여부"는 resolve 수보다 훨씬 더 흔들린다.
- **수리 루프:** (b) − (a) = +3 (1회차 대비) / +2 (2회차 대비). (b)에서만 resolved인 astropy-14995·django-11001은 첫 시도 apply 실패 → 수리 1회 → 통과로 **기제 추적 가능한 복구 2건**. django-11964는 (a) 회차 간에도 뒤집힌 노이즈 인스턴스. 12개 첫 시도 apply 실패 중 4개 복구(3개 resolved), 8개는 최대 3회 수리 후에도 실패 → drop. 판정: **방향은 기여 쪽, 노이즈 바닥(±1) 위, CI(±17pp) 안 — 통계적으로 구별되지 않음.**
- **절단:** 4096 도달은 (a) 0~1건(11905), (b) 2건(11905, 11910). 둘 다 미해결 인스턴스라 resolve 수를 바꾸진 않았다. 1024 때 (a) 3건 절단 중 2건이 apply 오류였던 것과 대조.
- **hints 제거의 영향(통제 비교 아님):** (a) 11/30(09-11) → 8·9/30. 09-11에만 resolved: 14995(이번 (b)에서 수리로 복구), 11848, 12113. hints 효과인지 노이즈인지 이 데이터로 구분 불가.
- **(c)에 관하여:** 1단계 임베딩 복구 후의 v1은 09-11의 (c)와 다른 시스템이다. 복구된 v1으로 (c)를 다시 재는 것은 별도 결정(≈$0.3).
- **7B 파일럿(`evidence/swe_fair/pilot_7b/`)**: 세 조건 모두 0/10. 7B는 적용 가능한 diff 자체를 못 만들어 이 질문에 답할 수 없다.
