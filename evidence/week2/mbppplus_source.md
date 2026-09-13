# MBPP+ 출처·고정 (Week2-B0)

| 항목 | 값 |
|---|---|
| 데이터셋 | MBPP+ (EvalPlus), `MBPP_PLUS_VERSION = v0.2.0` |
| 원본 URL | https://github.com/evalplus/mbppplus_release/releases/download/v0.2.0/MbppPlus.jsonl.gz |
| 로컬 캐시 | `%LOCALAPPDATA%\evalplus\evalplus\Cache\MbppPlus-v0.2.0.jsonl` (2,592,747 bytes) |
| 데이터 sha256 | `ee1701c904eb306523280b5a38a661d13248d16dd92d2e4fe2de36b519d3c413` |
| evalplus 버전 | 0.3.1 (별도 venv `.venv-evalplus/`, 동결: `requirements-evalplus.txt`) |
| 받은 날짜 | 2026-09-13 |
| 과제 수 | 378 (Mbpp/2 … Mbpp/809) |
| 스펙 파일 | `benchmark_data/mbppplus/MbppPlus-v0.2.0.spec.json` (gitignore, 7,252,625 bytes) |
| 스펙 sha256 | `b6888ff46104e154a58b5b1f2cabf08729334eecea66cad681fb90843721e5ca` (2026-09-14 생성, `benchmark/mbppplus.py::SPEC_SHA256` 에 고정) |

## 판정 로직: 공식 재사용 방식

- 정답 출력·시간: evalplus venv 에서 공식 `get_mbpp_plus`(역직렬화 특수 케이스 포함) + `trusted_exec`(정답 실행) 로 생성 → `benchmark/mbppplus_gt.py`.
- 비교: `harmonet/mbppplus_compare.py` = `evalplus/eval/__init__.py::unsafe_execute` 의 mbpp 비교 블록 + `_special_oracle.py` 전사
  (집합 비교 8과제, not-None 3과제, 특수 오라클 4과제, float 자동 atol 1e-6, `np.allclose(rtol=1e-7)`, atol 상태 전이). 단순 `==` 아님.
- 시간제한: 공식과 같은 케이스별 `max(1s, 4×정답시간)` (호출 후 경과시간으로 판정) + 프로세스 전체 `min(60, Σ)+2s`.
- 하네스: 기존 함수형 하네스(임시 디렉터리·nonce·result.json·`-I`·최소 env) 에 프렐류드(비교 함수)를 **후보 exec 뒤에** 넣어 후보가 덮지 못하게.
- 동등성: `tests/test_mbppplus_equivalence.py` 15케이스 + 2 — 공식 `unsafe_execute` 를 evalplus venv 에서 그대로 호출하는 오라클
  (`tests/mbppplus_official_oracle.py`) 과 pass/fail 일치. **Windows 에는 SIGALRM·resource 가 없어 공식 채점기가 원래 돌지 않는다** —
  오라클은 그 두 플랫폼 가드만 no-op 으로 바꾸고 비교 블록은 손대지 않았다.
- 전수 확인: 공식 정답 376개를 우리 하네스로 채점 → base·hidden 375/376 pass (`mbppplus_canonical_check.txt`). 1건(Mbpp/793)은 plus 입력이
  0개라 hidden 이 `no_tests` — 데이터 자체의 성질이며 풀에서 제외.

## 분할

- visible(`tests`) = base_input 케이스(프롬프트에 노출된 assert 의 입력; 공식 "base" 판정과 동일 규칙). 3개 347과제, 4~7개 29과제 (스펙 376 기준).
- hidden(`hidden_tests`) = plus_input − base_input (repr 동일 입력 제거). 총 39,841 → 139 제거 → 39,473 (과제별 `n_dup_removed` 기록).
- 직렬화: repr ↔ 제한 eval(`inf/nan/Counter/set()` 만 허용, builtins 없음). 복원값이 원본과 `==`·같은 타입임을 전수 확인.

## 제외 (스펙 생성)

| 과제 | 사유 |
|---|---|
| Mbpp/255 | 정답 출력 repr 1,294,369,422 bytes (조합 폭발) > 상한 1MB |
| Mbpp/630 | 정답 출력 repr 11,383,632 bytes > 상한 1MB |

## 제외 (풀) → `benchmark/mbppplus_split.py`

G1 external 첫 20개(sanitized-MBPP id 2…61 중 스펙에 있는 것), 개발 스모크 5개(2,3,4,6,7), 특수 판정 과제 14개(집합 비교·not-None·특수 오라클;
164/295 는 v0.2.0 에 없음), plus 입력 0개(793). 스펙 376 − 30 − 1 = **345** → 프로브 60 (seed 20260913) → **확인 집합 285** (`confirm_ids_mbppplus.json`).

## 지표

`base_pass`(공개 base), `plus_only_pass`(히든 plus−base; **게이트·주지표**, `hidden_exposed=False` 가드 통과), `both_pass`(둘 다 = 공식 plus 판정과 동치).
공개 base 3개는 프롬프트에 1개만 노출되지만 원 MBPP 에선 3개 모두 노출되므로 base_pass 는 히든 통과율로 취급하지 않는다.

## 오염 주의

MBPP 원본은 2021년 공개, 학습 데이터 포함 가능성 높음. plus 입력은 2023년 생성이지만 같은 함수의 추가 입력이라 기억 효과를 완전히 배제하지 못한다
(docs/week1_notes.md 의 오염 주석 참조). 풀 프로브 [30%, 70%] 판정으로 천장·바닥만 배제한다.
