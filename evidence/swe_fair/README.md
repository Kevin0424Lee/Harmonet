# SWE-bench Lite — single vs harmonet 어블레이션 (진행 중)

핵심 질문: 어려운 과제에서 검증·수리(apply-check → 수리 프롬프트)가 "한 번 호출"을 이기는가?

## 조건 (세 개 모두 같은 모델·같은 인스턴스)
| 조건 | 어댑터 | 러너 옵션 | 의미 |
|---|---|---|---|
| (a) single_novalidate | single | `--no-validate-patches` | LLM 1회, 검증·수리 없음 |
| (b) single_validate | single | `--drop-invalid` (기본 수리 루프) | 검증·수리 루프만 추가 — HarmoNet 프롬프트 없이 |
| (c) harmonet_validate | harmonet | `--drop-invalid` | (b)에 HarmoNet 어댑터(프롬프트·구조)를 얹은 것 |

해석은 **이번 실행 안에서만** 한다:
- (a)→(b) = 검증·수리 루프의 기여
- (b)→(c) = HarmoNet 프롬프트/구조의 기여

검증·수리 루프는 `benchmark/swebench_g1.py`에 있으며 어댑터와 무관하게 적용된다.
기존 18/43/50 체인(2026-06, claude-haiku-4-5 via RunYourAI)은 **별도 참고값**으로만 기술하고 같은 표에 넣지 않는다 —
당시 파이프라인(옵션·프롬프트·컨텍스트 한도)이 지금과 동일하다는 것을 증명할 수 없기 때문이다.

## pilot_7b/ — qwen2.5-coder:7b-32k, 인스턴스 0–9 (2026-09-11)
| 조건 | 적용되는 패치 | resolved | 평균 토큰 |
|---|---|---|---|
| (a) | 8/10 (2 apply 오류) | **0/10** | 4,071 |
| (b) | 2/10 (8 drop) | **0/10** | 9,345 |
| (c) | 1/10 (9 drop) | **0/10** | 10,258 |

7B는 적용 가능한 diff 자체를 거의 못 만든다. 수리 루프는 토큰을 2.3~2.5배 쓰고 거의 구제하지 못한다.
바닥이 0이라 조건 간 변별이 불가능 → 기존 18/43/50 실행과 같은 모델(claude-haiku-4-5)로 재실행해야 한다.

## 실행 전 확인된 인프라 문제 (수정 완료)
- `swebench_g1.py`: `--repo-cache` 상대경로면 Windows에서 apply-check가 WinError 267로 전부 INVALID 처리됨 → `.resolve()` 고정.
- Ollama 기본 컨텍스트가 프롬프트를 ~2k 토큰으로 잘라냄 → `qwen2.5-coder:7b-32k` 파생 모델(num_ctx 32768). G1은 절단 없음 확인(COMPARISON.md §1-A).
- 평가는 WSL Ubuntu의 swebench 5.0.2 + Docker Desktop. 인스턴스 이미지 ~2.9GB/개 → 100개는 배치·정리 필요.

## 사전 등록 (2026-09-11, 30개 실행 전 고정)

**1차 관찰 대상: 수리 발동률.** 3개 비용 확인에서 9/9가 첫 시도에 `git apply` 통과 → 수리 호출 0회.
30개에서도 0회면 (a)와 (b)는 구조적으로 동일한 실행이며, 그 사실 자체가 결과다.

**통계적 한계.** n=30이면 resolve율의 95% 신뢰구간 반폭이 약 ±18pp. 근소한 차이는 "우위"가 아니라 **"구별되지 않음"**으로 보고한다.

**해석 규칙 (결과 보기 전 고정).**
| 관찰 | 해석 |
|---|---|
| (a)≈(b)≈(c) 이고 수리 0회 | apply-check 수리 파이프라인은 이 모델·과제에서 무의미 |
| (b)>(a) | 검증·수리 루프의 기여 |
| (c)>(b) | HarmoNet 프롬프트/구조의 기여 |
| (c)<(a) | 기제가 해로움 |

**범위 한계.** 이 실험은 **컨텍스트 검색을 테스트하지 않는다.** 세 조건 모두 같은 oracle 파일 컨텍스트(`_make_prompt`)를 받는다.
과거 체인에서 17→43을 만든 것은 컨텍스트 검색이었고, 여기서 분리하는 것은 수리 쪽 개입뿐이다.
따라서 셋이 같게 나와도 "모든 기제가 무의미"로 일반화하면 안 된다. 그 경우 다음 실험은 (d) single + 컨텍스트 검색.

비용 확인(0–2, 3조건): prompt 29,356 / completion 3,083 토큰 = $0.045. 30×3 예상 ~$0.45 (상한 ~$0.9). 승인됨.

## haiku 실행 (다음 단계)
```powershell
# 1) 키 확인 (사용자 스코프 ANTHROPIC_API_KEY, sk-ant-… 형식)
powershell -File swe_fair\verify_anthropic.ps1   # measured=True 확인
# 2) 비용 확인용 3개
.\swe_fair\run_swe_gen.ps1 -Cond single_novalidate -Offset 0 -Limit 3 -Backend anthropic
# 3) 30개 × 3조건 → eval.sh로 평가 → 기존 100개 결과에서 0–29 구간만 추출해 비교
```

## haiku_0_30/ — 결과 (2026-09-11) → 본문은 `evidence/g1_fair/COMPARISON.md` §11

| 조건 | resolved | apply 실패 | 수리 복구 | 수리 호출 | 평균 토큰 | 비용 |
|---|---|---|---|---|---|---|
| (a) single_novalidate | 11/30 | 7 (하네스 오류) | — | 0 | 4,408 | $0.187 |
| (b) single_validate | 14/30 | 11 | 5 | 13 | 7,670 | $0.311 |
| (c) harmonet_validate | 11/30 | 9 | 4 | 9 | 6,831 | $0.257 |

판정: (a)→(b) +3 (수리로 살린 패치 2개 포함, CI 안 → "구별되지 않음"이나 방향은 기여). (b)→(c) −3 → HarmoNet 프롬프트/구조의 기여 없음. (a)=(c).

## 참고값 (같은 표에 넣지 않음)
2026-06 "컨텍스트" 조건(RunYourAI/claude-haiku-4-5, 100개) 중 **같은 0–29 구간**만 추출:
컨텍스트 43/100 실행 → 0–29에서 **14/30**, 시맨틱 수리 50/100 실행 → 0–29에서 15/30 (+django-11630).
당시 14개 resolved 집합은 이번 (b) single_validate의 14개와 **정확히 동일한 인스턴스**다.
파이프라인 동일성을 증명할 수 없어 비교표에는 넣지 않지만, 당시 수치가 apply-check 수리 루프 수준이었다는 정황이다.

## 다음 실험
(d) single + 컨텍스트 검색 — 과거 17→43의 주역을 single 어댑터 위에서 분리.
Docker 인스턴스 이미지 30개(~90GB)는 (d) 재사용을 위해 남겨 둠. C: 여유 63GB.
