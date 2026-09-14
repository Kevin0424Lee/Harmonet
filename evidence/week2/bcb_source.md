# BigCodeBench 출처·고정·적격성 (Week2-C0)

| 항목 | 값 |
|---|---|
| 데이터셋 | BigCodeBench **Complete** (`complete_prompt`), Full 1,140 |
| HF 저장소 / revision | `bigcode/bigcodebench` @ `b74c0d0bf70d2c0bc459be537895cca163007f1a` (main, 2025-04-30) |
| 파일 | `data/v0.1.4-00000-of-00001.parquet` (2,362,110 bytes), sha256 `d9a4965821c9507ebdfb551c288656b2d5fe553234f5183044333ca8a4018267` |
| 사용 필드 | task_id, complete_prompt, doc_struct, entry_point, libs, canonical_solution(적격성 전용), test(히든 채점 전용) |
| 채점 이미지 | `bigcodebench/bigcodebench-evaluate` **v0.2.4** @ `sha256:a3cd34ec3840a49d6b7afb240f4bdd47c350bc5991043fd0a91773830f7cd405` (2025-02-23, 15.1GB, Python 3.10.16, bigcodebench 0.2.4) |
| 컨테이너 옵션 | `--network none --memory 8g --cpus 2 --entrypoint python3 … -I harness.py` (Docker Desktop 26.0.0 / WSL2) |
| 판정 함수 | (C0) 공식 `bigcodebench.eval.untrusted_check` 그대로 → (D2) `harmonet/bcb_check.py` d2.1: 공식 환경 헬퍼(create_tempdir/safe_environment/reliability_guard/swallow_io/time_limit) + **실행 수 검사**(클린 프로세스에서 센 expected_tests == testsRun ∧ skipped 0 ∧ 실패·오류 0 ∧ 자식 exitcode 0) + unittest 참조 사전 바인딩. 공식 채점기는 실행 수를 검사하지 않는다. 과제 타임아웃 = 공식 max(240, gt)+1 = 241s |
| 날짜 | 2026-09-14 |

## 노출 경계
- 모델 프롬프트 = `complete_prompt` 그대로. `test`·`canonical_solution` 은 `BcbTask._test/_canonical` 에만 있고 spec 의 `hidden_tests` 와
  적격성 배치(`bcb_eligibility.py`)만 읽는다. `hidden_exposed=False`. 테스트 `tests/test_bcb.py::test_prompt_never_contains_test_or_canonical`.
- 후보 코드는 컨테이너 안 공식 `create_tempdir`/`safe_environment`/`reliability_guard` 아래에서 실행되고 nonce·결과 경로를 볼 수 없다
  (하네스가 stdin 으로 받아 메모리에만 둠; 결과 파일은 `result_<nonce8>.json`).

## 가시 검증 신호 (관문 1)
가시 테스트 = `doc_struct["examples"]` 의 doctest 블록을 `unittest.TestCases` 로 감싼 모듈 1개 → 히든과 **같은** 공식 `untrusted_check` 로 판정.
채택 조건: (a) 기대 출력이 있는 예제 ≥1, (b) 정적 스크린 통과 — 예제 텍스트에 난수·시간·네트워크·파일시스템·플롯 토큰
(`benchmark/bcb.py::_NONDET_RE`) 없음, (c) 공식 이미지에서 canonical(complete_prompt + canonical_solution, 공식 get_groundtruth 와 같은 조립)로
doctest 를 2회 돌려 둘 다 pass. canonical 은 이 판정에만 쓴다. 최종 채점 `test` 는 관문 1 에서 읽지 않는다.

## 실행 안정성 (관문 2)
관문 1 과제의 canonical 을 공식 `test` 로 2회 채점 → 둘 다 pass.

## 결과 (2026-09-14)
배치: `benchmark/bcb_eligibility.py` → 공식 이미지 1개 컨테이너에서 `benchmark/bcb_batch_harness.py` (스레드 4, 과제마다 공식 `untrusted_check` 4회), 1,348s.
원본 `benchmark_data/bcb/work/results.json`(gitignore), 집계 `evidence/week2/bcb_eligibility.json`.

| 단계 | 과제 수 |
|---|---|
| 전체 (Complete) | 1,140 |
| doctest 예제에 기대 출력 ≥1 | 1,021 |
| 정적 스크린 통과 (난수·시간·네트워크·FS·플롯 토큰 없음) | 637 — 걸린 토큰 상위: seed 151, random 131, Axes 115, plt 34, http 27, tempfile 24 |
| **관문 1** canonical 로 doctest 2회 모두 pass | **412** (≥ 260 통과). fail/fail 224 (예시용 경로·가상 파일 등 실행 불가 예제), pass/fail 1 (불안정) |
| **관문 2** canonical 을 공식 test 로 2회 모두 pass | **410**. 제외 2: BigCodeBench/821·823 (fail→pass, 불안정) |
| 개발용 ID 제외 (BigCodeBench/0·1·2 중 관문 통과분: /0) | **409 = 적격 풀** |
| 프로브 60 (seed 20260913) / 확인 집합 | 60 / **349** (≥ 200) — `probe_ids_bcb.json`; 확인 집합은 프로브 판정 통과 뒤 동결 |

참고: 검사한 637개 중 공식 test 가 불안정하거나 실패한 canonical 은 21개(fail/fail 16, fail/pass 3, timeout/timeout 2) — 관문 1 통과분에는 2개만 겹쳤다.
공식 test 실행 시간 중앙값 0.38s, 최대 263s(타임아웃 241s 초과분 포함).

## 개발·디버그에 쓴 ID
BigCodeBench/0 (로더 자체 점검, kind bcb 스모크, 적대 테스트, 사전 점검 canonical), BigCodeBench/1 (러너 mock 스모크, `tests/test_bcb.py`), BigCodeBench/2 (예비), BigCodeBench/3·4·9 (D5 arms 스모크). 풀에서 제외.

## D2 ⑤ 재적격성 (2026-09-14)
필터 v2 + 채점기 d2.1 로 재실행 (1,059s): 정적 통과 630, 관문 1 **411**, 관문 2 **408**, 적격 **404** (개발용 6 제외). 변경 상세는 `pool_probe.md` "D2 ⑤ 재적격성 기록". 적격성 캐시 `benchmark_data/bcb/work/eligibility_cache.json` (키 = revision·이미지 digest·필터 버전·채점기 버전).
