# 백엔드 선택 — RunYourAI를 못 쓸 때

## 결론 먼저

**Ollama를 OpenAI 호환 엔드포인트로 쓰는 것이 지금 최선이다.** 무료이고, 추정치가 아닌
**실제 토큰 수**를 반환하며, 다섯 시스템 전부를 같은 엔드포인트·같은 모델로 돌릴 수 있다.

---

## 왜 Ollama로 충분한가

이번 재측정의 목적은 **비교의 공정성**을 확보하는 것이지 예전 절대값을 재현하는 게 아니다.
"HarmoNet이 LangGraph보다 토큰을 적게 쓰는가"는 다섯 시스템이 같은 모델을 쓰면 답이 나온다.
모델이 Haiku든 Qwen2.5 7B든 상관없다.

게다가 Ollama는 `prompt_eval_count` / `eval_count`를 반환하는데, 이건 **모델 토크나이저가
센 실제 토큰 수**다. 단어수×1.3 같은 추정이 아니다. 즉 `token_source=measured`가 된다.

**단, 논문에 실을 최종 수치는 상용 모델로 다시 뽑는 것이 좋다.** 2단계로 간다.

| 단계 | 백엔드 | 비용 | 목적 |
|---|---|---|---|
| 1단계 | Ollama | 0원 | 측정이 공정해졌는지 확인, 결론이 바뀌는지 확인 |
| 2단계 | Anthropic 또는 OpenAI API | 약 1~2만원 | 논문용 최종 수치 |

1단계에서 우위가 사라지면 2단계에 돈을 쓸 필요가 없다. 순서가 중요하다.

---

## 설치

```powershell
# 1. Ollama 설치 — https://ollama.com/download 에서 Windows 설치 파일
# 2. 모델 받기 (코딩 과제용 권장)
ollama pull qwen2.5-coder:7b
# 가벼운 편이 좋으면: ollama pull qwen2.5:3b
# 3. 서버 확인 (설치 시 자동 실행됨)
curl http://localhost:11434/api/tags
```

7B 모델은 HumanEval 정답률이 낮게 나온다. **그게 오히려 낫다** — 기존 실험의 문제 중
하나가 모든 시스템이 100%를 찍어 변별력이 없었던 것이다. 7B에서는 차이가 드러난다.

---

## HarmoNet 설정

```powershell
$env:HARMONET_LLM_BACKEND="openai_compatible"
$env:OPENAI_COMPAT_BASE_URL="http://localhost:11434/v1"
$env:OPENAI_COMPAT_MODEL="qwen2.5-coder:7b"
$env:OPENAI_COMPAT_API_KEY="ollama"      # 더미값, Ollama는 검사하지 않음
$env:OPENAI_COMPAT_TIMEOUT_SECONDS="600" # 로컬 추론은 느리다
```

그다음 반드시:

```powershell
python verify_usage.py
```

`measured=True`가 나와야 한다. Ollama의 `/v1` 호환 레이어가 `usage`를 반환하므로
정상이면 통과한다. 만약 `measured=False`가 나오면 네이티브 백엔드로 바꾼다:

```powershell
$env:HARMONET_LLM_BACKEND="ollama"
$env:OLLAMA_MODEL="qwen2.5-coder:7b"
python verify_usage.py
```

네이티브 경로는 `prompt_eval_count`/`eval_count`를 직접 읽으므로 이쪽도 실측이다.
**둘 중 통과하는 쪽을 쓰면 된다.**

---

## 베이스라인 세 개도 같은 엔드포인트로

공정 비교의 핵심이다. 어댑터들이 RunYourAI를 바라보고 있으므로 Ollama로 돌려야 한다.

```powershell
# 세 어댑터가 공통으로 읽는 OpenAI 호환 설정
$env:OPENAI_API_KEY="ollama"
$env:OPENAI_BASE_URL="http://localhost:11434/v1"
$env:OPENAI_MODEL="qwen2.5-coder:7b"
```

**Claude Code가 확인해야 할 것:** 각 어댑터가 이 환경변수를 실제로 읽는지.

- `benchmark/agents_langraph.py` — `_try_ollama()` 경로가 이미 있다. `ChatOllama` 또는
  `ChatOpenAI(base_url=...)` 중 어느 쪽이든 `usage_metadata`가 채워지는지 확인
- `benchmark/agents_crewai.py` — `RunYourCrewLLM`이 base_url을 받도록 되어 있는지 확인.
  안 되면 litellm 형식(`ollama/qwen2.5-coder:7b`)으로 모델명을 주는 방법이 있다
- `benchmark/agents_autogen.py` — `_model_config()`가 `RUNYOURAI_MODEL`을 하드코딩해서
  읽는다. base_url과 model을 Ollama로 바꿀 수 있게 수정이 필요할 수 있다

**세 어댑터 중 하나라도 Ollama로 못 돌리면, 그 시스템은 이번 비교에서 제외하고
그 사실을 결과에 명시한다.** 다른 모델로 돌린 값을 같은 표에 넣으면 안 된다.
(그게 애초에 이 재측정을 하는 이유다.)

최소 조건: **HarmoNet v2 + LangGraph + CrewAI 세 개**만 같은 모델로 돌아가도
핵심 질문("그래프 오케스트레이션 대비 우위가 실재하는가")에는 답할 수 있다.

---

## 대안: 유료 API를 바로 쓰는 경우

시간을 아끼고 싶고 1~2만원을 쓸 수 있다면 Anthropic 직접 호출이 가장 깔끔하다.

```powershell
$env:HARMONET_LLM_BACKEND="anthropic"
$env:ANTHROPIC_API_KEY="sk-ant-..."
python verify_usage.py
```

Anthropic API는 `usage.input_tokens`/`output_tokens`를 항상 반환하므로 실측이 보장된다.
패치의 `record_from_response`가 이 형식을 이미 처리한다.

참고: ChatGPT Plus 구독은 API 접근이 아니다. Codex 크레딧도 별개다.
OpenAI Student Collective에 최종 합격하면 크레딧이 나올 수 있으니, 급하지 않다면
1단계(Ollama)를 먼저 돌리고 결과를 본 뒤 결정하는 편이 낫다.

---

## 실행 순서 요약

1. Ollama 설치 + 모델 pull
2. HarmoNet 환경변수 설정 → `python verify_usage.py` → **measured=True 확인**
3. 베이스라인 어댑터가 같은 엔드포인트를 보는지 확인·수정
4. mock 스모크로 배선 확인 (`RERUN.md` Task 4)
5. 본 실행 — `--limit`을 10 정도로 줄여 시작 (로컬 추론은 느리다)
6. 잘 돌면 20×3으로 확대
7. `compare_runs.py`로 구/신 비교

로컬 7B로 humaneval+mbpp 20문제 × 3회 × 5시스템이면 수 시간 걸릴 수 있다.
먼저 `--limit 5 --repeats 1`로 끝까지 도는지 확인한 뒤 확대하는 것이 안전하다.
