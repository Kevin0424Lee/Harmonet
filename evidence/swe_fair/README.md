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

## haiku 실행 (다음 단계)
```powershell
# 1) 키 확인 (사용자 스코프 ANTHROPIC_API_KEY, sk-ant-… 형식)
powershell -File swe_fair\verify_anthropic.ps1   # measured=True 확인
# 2) 비용 확인용 3개
.\swe_fair\run_swe_gen.ps1 -Cond single_novalidate -Offset 0 -Limit 3 -Backend anthropic
# 3) 30개 × 3조건 → eval.sh로 평가 → 기존 100개 결과에서 0–29 구간만 추출해 비교
```
