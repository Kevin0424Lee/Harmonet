# 재측정 실행 지시서 (Claude Code용)

이 파일은 HarmoNet 저장소 루트에 두고 Claude Code에게 읽히는 용도다.
목적: 벤치마크 토큰 측정을 전 시스템 동일 기준으로 바꾼 뒤 G1을 재측정한다.

---

## 배경 (왜 이걸 하는가)

기존 G1 비교는 시스템마다 다른 방법으로 토큰을 집계했다.

| 시스템 | 집계 방식 | 시스템 프롬프트 | 에이전트 간 전달 |
|---|---|---|---|
| LangGraph | `usage_metadata` — API 실측 | 포함 | 포함 |
| CrewAI | `usage_metrics` — API 실측 | 포함 | 포함 |
| AutoGen | 전체 프롬프트 단어수 추정 | 포함 | 포함 |
| HarmoNet v1 | 단어수×2 + 추정, 통신=0 선언 | 미포함 | **0으로 정의** |
| HarmoNet v2 | 단어수×1.3, 사용자 프롬프트만 | **미포함** | 해당 없음 |

근본 원인은 `harmonet/llm.py`의 `generate()`가 `response.usage`를 버리고 문자열만
반환한 것이다. HarmoNet은 구조적으로 실제 토큰을 알 수 없었다.

따라서 기존 "LangGraph 대비 87.5% 절감" 수치는 **인용 금지**이며, 재측정 후의 값으로
대체한다. LangGraph 대비 우위는 살아남을 가능성이 높지만, CrewAI 대비 24% 우위
(295 vs 224)는 뒤집힐 가능성이 크다.

---

## 작업 목록

### Task 1. 패치 적용

`01-fair-measurement.patch`를 저장소 루트에 둔 뒤:

```bash
git checkout -b fair-measurement
git am 01-fair-measurement.patch
```

`git am`이 충돌하면 `git am --abort` 후 `git apply --3way 01-fair-measurement.patch`를
시도한다. 그것도 실패하면 패치 내용을 읽고 아래 변경을 직접 적용한다.

**패치가 하는 일:**

1. `harmonet/usage.py` 신규 — 스레드 안전 `UsageMeter`. API 실측 usage를 누적하고
   `measured` 플래그로 추정치 혼입을 표시한다.
2. `harmonet/llm.py` — 6개 호출 지점에서 `METER.record_from_response(response)` 호출
   (OpenAI / OpenAI호환·RunYourAI / Anthropic, 각 동기·비동기).
   Mock·Ollama는 `_wrap_estimating`으로 감싸 추정치를 `estimated=True`로 기록.
3. `benchmark/agents_harmonet.py` — `prompt_tokens = len(split())*2`와 "통신 토큰 0"
   선언을 삭제하고 `METER.snapshot()` 사용. `run()` 진입 시 `METER.reset()`.
4. `benchmark/agents_harmonet_v2.py` — `_call_llm`이 추정 대신 계측기 델타 반환.
   시스템 프롬프트가 포함된다. 결과에 `token_source` 추가.
5. `benchmark/external_g1.py` — 결과 CSV에 `token_source` 컬럼 추가.
   `G1_DISABLE_EVAL_REPAIR=1`로 eval-repair 경로를 끌 수 있게 함.

### Task 2. 회귀 확인

```bash
python -m pytest tests/ -q
```

기대: 전부 통과. `test_operational_g2.py`가 `fastapi` 미설치로 실패하면
`pip install fastapi`로 해결하거나 `--ignore=tests/test_operational_g2.py`로 제외한다.
(참고 환경에서 157 passed, 1 skipped 확인함)

### Task 3. ⚠️ 실측 usage 수신 확인 — 본 실험 전 필수

`verify_usage.py`를 저장소 루트에 두고 실제 백엔드로 실행한다.

```bash
# Windows PowerShell
$env:HARMONET_LLM_BACKEND="runyourai"
python verify_usage.py
```

**이 단계가 이 작업 전체에서 가장 중요하다.** 프로바이더가 `response.usage`를
반환하지 않으면 패치를 적용해도 전부 추정치가 되어, 비싼 본 실험이 헛수고가 된다.

- `✅ 통과` → Task 4로 진행
- `⚠️ measured=False` → **본 실험을 돌리지 말 것.** RunYourAI 같은 라우터는 usage를
  생략하는 경우가 있다. Anthropic 또는 OpenAI 직접 호출로 백엔드를 바꿔 재확인한다.
- `❌ 실패` → 패치 적용이 불완전하다. `harmonet/llm.py`에서
  `METER.record_from_response` 위치를 확인한다.

### Task 4. mock 스모크 (비용 0)

```bash
$env:HARMONET_LLM_BACKEND="mock"
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval --limit 2 --repeats 1 `
  --adapters harmonet_v2,harmonet --output smoke_fair.json
```

확인: 생성된 `smoke_fair.csv`에 `token_source` 컬럼이 있고 값이 `estimated`인지
(mock이므로 정상). 컬럼이 없으면 Task 1의 5번이 적용되지 않은 것이다.

### Task 5. 본 실험 — 수리 경로 포함

```bash
$env:HARMONET_LLM_BACKEND="runyourai"   # Task 3에서 통과한 백엔드
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval,mbpp --limit 20 --repeats 3 `
  --adapters harmonet_v2,harmonet,langraph,autogen,crewai --output g1_fair_20x3.json
```

실행 중 확인: HarmoNet 행의 `token_source`가 `measured`여야 한다.
`estimated`가 나오면 즉시 중단하고 Task 3으로 돌아간다.

### Task 6. 본 실험 — 수리 경로 제외

`external_g1.py`는 `repair_after_eval` 메서드를 가진 어댑터에만 2차 시도를 준다.
그 메서드는 HarmoNet v2에만 있으므로, 정확도 비교가 "2회 시도 vs 1회 시도"가 된다.
대칭 조건도 함께 측정한다.

```bash
$env:G1_DISABLE_EVAL_REPAIR="1"
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval,mbpp --limit 20 --repeats 3 `
  --adapters harmonet_v2,langraph,autogen,crewai --output g1_fair_norepair_20x3.json
Remove-Item Env:\G1_DISABLE_EVAL_REPAIR
```

### Task 7. 비교표 생성

`compare_runs.py`를 저장소 루트에 두고:

```bash
python compare_runs.py evidence/g1/g1_v2_final_4way_20x3.csv g1_fair_20x3.csv
```

출력에 포함되는 것: 시스템별 구/신 평균 토큰과 변화율, 정확도, 측정 출처,
LangGraph 대비 절감률, 추정치 혼입 경고.

### Task 8. 결과 정리

`evidence/g1_fair/`를 만들고 다음을 넣는다.

- `g1_fair_20x3.{json,csv}`, `g1_fair_norepair_20x3.{json,csv}`
- `verify_usage_output.txt` — Task 3 출력 (실측 증빙)
- `COMPARISON.md` — Task 7 출력 + 아래 항목 서술
  - 구 측정이 왜 비교 불가였는지 (집계 방식 표)
  - 재측정 후 각 시스템 대비 우위가 유지되는지 여부
  - 수리 포함/미포함 조건 차이
  - AutoGen이 여전히 추정치라면 그 사실

---

## 알려진 이슈와 대응

| 증상 | 원인 | 대응 |
|---|---|---|
| `git am` 실패 | 로컬 HEAD가 GitHub와 다름 | `git apply --3way` 또는 수동 적용 |
| `verify_usage.py`가 measured=False | 라우터가 usage 생략 | 백엔드를 Anthropic/OpenAI 직접 호출로 변경 |
| HarmoNet 토큰이 이전보다 크게 증가 | **정상.** 시스템 프롬프트와 통신 토큰이 이제 포함됨 | 그대로 보고 |
| CrewAI 대비 우위 소멸 | 예상된 결과 | 정직하게 보고. 주장을 "그래프 오케스트레이션 대비"로 한정 |
| AutoGen만 `estimated` | AutoGen 어댑터는 자체 추정 사용 | 여유 있으면 AutoGen SDK usage 연결, 없으면 명시 |

---

## 하지 말 것

- 재측정 전의 수치(224.4 토큰, 87.5% 절감)를 어디에도 인용하지 않는다.
- 출처가 다른 값(`measured`와 `estimated`)을 한 표에서 비교하지 않는다.
- 결과가 불리하게 나왔다고 집계 방식을 되돌리지 않는다.

---

## 완료 기준

- [ ] `verify_usage.py` 통과 (measured=True)
- [ ] `g1_fair_20x3.csv`의 HarmoNet 행 `token_source`가 전부 `measured`
- [ ] 수리 포함/미포함 두 조건 모두 측정 완료
- [ ] `COMPARISON.md`에 구 대비 변화와 결론 변경 여부 서술
- [ ] 커밋 후 푸시
