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
