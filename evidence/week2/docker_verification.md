# Docker 전체 경로 재검증 (Week2-D3, 2026-09-14)

## 실행 환경
| 항목 | 값 |
|---|---|
| 호스트 OS | Windows-10-10.0.19045 (Docker Desktop, WSL2 백엔드) |
| Docker | client 26.0.0 / server 26.0.0, linux/amd64 |
| 이미지 | `bigcodebench/bigcodebench-evaluate@sha256:a3cd34ec3840a49d6b7afb240f4bdd47c350bc5991043fd0a91773830f7cd405` (v0.2.4, image id `b13b0bb97861…`, 2025-02-23, 15.1GB, Python 3.10.16, bigcodebench 0.2.4) |
| 호스트 Python | 3.10.10 |
| 채점기 | `harmonet/bcb_check.py` harmonet-bcb-check-d2.1, 컨테이너 옵션 `--network none --memory 8g --cpus 2 --entrypoint python3 -I` |

## Docker 표시 테스트 (실제 Docker 에서 실행)
| 파일 | 테스트 | 결과 |
|---|---|---|
| tests/test_bcb.py | `test_bcb_official_check_in_image_pass_and_fail` (canonical pass / 오답 fail) | passed |
| tests/test_bcb_adversarial.py | (d) canonical pass ∧ testsRun == expected | passed |
| | (a) TestCase.run / TestSuite.run no-op 패치 → False | passed |
| | (b) `__init_subclass__` 로 skip 주입 → skipped>0 → False | passed |
| | (c) `sys.modules['unittest']` 교체 → False | passed |
| | (e) 정답 뒤 스레드 os._exit(3) → False, task_func 안 os._exit(0) → False | passed |
| tests/test_budget_runloop.py | `test_timeout_kills_and_removes_container` (무한 루프 → timeout → `docker ps -a` 에 이름 없음) | passed |

**Docker 표시 7 passed / 0 skipped / 0 failed** (이 환경). 같은 파일들의 비-Docker 테스트 11 passed.
전체 스위트: **289 passed / 0 skipped / 0 failed** (`pytest tests --ignore=tests/legacy`, 190s).

## Docker 없는 환경의 표시 (조용한 pass 금지)
`PATH` 에서 docker 를 뺀 채 같은 파일들을 돌리면: **11 passed / 7 skipped / 0 failed**, skip 사유가 각각 표시된다:
- `skipped: docker unavailable (공식 이미지 안 채점 테스트)` ×1
- `skipped: docker unavailable (BCB 적대 테스트는 공식 이미지가 필요)` ×5
- `skipped: docker unavailable (D1 ④ 컨테이너 정리 테스트는 실제 Docker 가 필요)` ×1
판정 로직의 skip 조건은 `docker` 실행 파일 존재 ∧ `docker info` rc==0 (둘 다 실패면 skip). C0 의 "docker 없으면 실패" 규칙은 D3 에서 "명시적 skip + 사유" 로 통일.

## 같이 확인된 경로 (테스트 외)
- 적격성 배치 630 과제 × 4 판정 in-image (1,059s) → `bcb_eligibility.json` (D2 ⑤).
- 프로브 120 후보 in-image 재채점 (453s) → `RESCORE_bcb.md`, 뒤집힘 0.
- arms 스모크 3 과제 × 6 arm (mock LLM, in-image 채점) → `scripts/arms_smoke.py` OK (D5).
- 사전 점검 `bcb_preflight()`: docker info + digest 일치 + BigCodeBench/0 canonical pass (D1 ②).

## 이번 검증에서 드러난 것
- 스레드에서 fork 한 multiprocessing 자식은 이 이미지의 Python 3.10 에서 **정상 종료해도 exitcode 1** — D2 exitcode 규칙과 충돌해 canonical 전부 fail 로
  나왔다. 배치를 비데몬 워커 프로세스로 바꿔 해결. 공식 채점기는 exitcode 를 보지 않아 이 문제가 드러나지 않았다.
- `reliability_guard` 아래서 자식이 죽어도 `Process.join(timeout)` 이 타임아웃까지 기다린다(손자가 sentinel 파이프를 물고 있음). `is_alive()` 폴링으로 교체.
- Windows 에서 docker CLI 를 kill 해도 파이프가 닫히지 않아 컨테이너 종료까지 대기 → 타임아웃 처리는 `docker kill <name>` 이어야 한다 (D1 ④).
