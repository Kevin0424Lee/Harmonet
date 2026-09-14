# Week 1 진행 메모 — Part C 설계에 반영할 항목

Part A 진행 중 확정된 사실과, 2주차 설계(`docs/week2_design_draft.md`)에 넣어야 할 항목의 누적 목록.

## Part C "실행 환경" 항목
- `evidence/*/run_*.ps1` 등 기존 실행 스크립트는 A2 이후 `HARMONET_ALLOW_NO_REDIS=1` 없이는 즉시 `RuntimeError`.
  재실행 시 반드시 추가. Mock 은 `HARMONET_LLM_BACKEND=mock` 명시 필요 (자동 폴백 없음).
- legacy 메커니즘(Kuramoto·TDA·SOC)은 `HARMONET_LEGACY_MECHANISMS=1` 일 때만. 기본 실행은 코사인 + 적응형 δ 게이트.

## Part C 공정성 항목
- `benchmark/agents_harmonet_v2.py:repair_after_eval` 는 외부 채점기의 실패 출력(`eval_error`, 히든 테스트 결과)을
  프롬프트에 넣는다 — N3 와 같은 누출 패턴. A4c 부터 **기본 차단** (`G1_DISABLE_EVAL_REPAIR` 기본 1, 켜려면 `=0` 명시) 이고 켜서 실행하면 trace 에 `trigger=eval:hidden`, `TaskState.leak_risk=true` 라벨.
- v1 어댑터의 키워드 기반 repair 경로(`benchmark/agents_harmonet.py`, `HARMONET_REPAIR_KEYWORD_THRESHOLD`)는
  HarmoNet 에만 있는 2차 LLM 호출. 조건 간 비교 시 끄거나 전 조건에 동일 적용.

## Part C 전제 조건 (2주차 첫 작업)
- validator 가 실행할 **공개** 테스트: HumanEval docstring 의 `>>>` 예제를 doctest 로 추출해 `task_spec["tests"]` 에 넣는다.
  현재 G1 러너는 채점용 히든 테스트를 넣지 않으므로(누출 방지) validator 는 AST + 진입점 검사까지만 수행.

## A1~A3 관찰 기록
- Architect 오배송 (정정): A0 에서 architect 가 builder 피드백 씨앗에 공명하는 것을 봤고 "실행"으로 보고했으나,
  실행은 아니었다(당시 호출 수 Architect 0). A3 후 재현: `target_role` 필터를 끄고 피드백 문구를 A0 당시
  "Security validation required: FastAPI JWT … OWASP audit" 로 되돌리면 **3/3 회 architect 공명**(유사도 0.636 > δ 0.20),
  단 claim 우선순위 지연이 유사도 기반이라 validator(0.835, 8ms)가 항상 먼저 선점하고 architect(18ms)는 스킵.
  결론: **코사인 게이팅은 씨앗 문구에 민감하다. 검증 요청을 보안 감사처럼 쓰면 Architect(sim 0.636)로 오배송된다.**
  비결정성은 없었다(Kuramoto on/off, 필터 on/off 모두 반복 동일). 현재는 `target_role` 로 구조 차단.
  주 경로의 마지막 난수 원천(감지기 초기 위상, `resonance.py:71`)은 legacy 가 아닐 때 0 으로 고정.
- validator 결과 씨앗의 `verification` off-by-one → A4 에서 판정을 인자로 직접 전달해 수정 (`agent.py:_scatter_feedback_seed(…, verification)`).

## Part C 지연 측정 항목
- `benchmark/agents_harmonet.py` 와 데모는 legacy 플래그가 없어도 `KuraMotoCoupler.step()` / `sync_phase()` 를 매 틱 호출한다
  (에이전트는 무시). 지연시간 비교에 이 낭비 연산이 섞이지 않게 v1 어댑터에서 제거하거나 측정에서 분리.

## A4 trace 비용 귀속 규칙 (v1 어댑터)
- v1 은 세 에이전트가 같은 틱에서 동시에 도는 구조라 METER 델타를 호출 단위로 분리할 수 없다. 틱 단위 델타를 그 틱의
  builder 행동에 귀속하고 나머지 LLM 행동은 0 으로 기록한다. 2주차 비교(단일 vs 자기수정 vs 전문가)는 v2/single 처럼
  호출이 직렬인 어댑터로 하는 것이 안전하다.

## A5 관찰
- LLM 역할은 코드에 두 개뿐: `builder`(build/self_revise/eval_repair 호출), `reviewer`(v2 의 LLM validator = expert_review).
  `AgentRole` 의 architect/validator/observer 는 v1 필드 역할이지 LLM 역할이 아니다 → `get_llm_client("architect")` 는 ValueError.
  v1 어댑터는 `get_llm_client()`(기본, role="default") 그대로 — 비용 귀속도 tick_aggregate 유지.
- v2 의 reviewer 단계는 **open-ended 과제(api_design 등)에서만** 돈다. HumanEval/MBPP 같은 실행 가능 코드 과제는
  builder-only 이므로 2주차 "전문가 추가" 조건은 v2 프로파일 로직을 우회해 명시적으로 호출해야 한다.
- 지정 모델 존재 확인은 무료 조회로 한다: Ollama `/api/tags`, OpenAI/호환/Anthropic `models.retrieve`. 지정하지 않은 역할(기본 모델)은
  조회를 생략한다 (기존 G1 실행 흐름을 바꾸지 않기 위해).
- `Action.model` 은 실백엔드에서 `response.model` (Ollama /v1 실측: `qwen2.5-coder:7b`), mock 은 설정명 echo (`mock-a`).

## A7 검증기 한계 (subprocess 샌드박스)
- **(A7b 정정)** A7 보고의 "argv 위조도 nonce 불일치로 aborted" 는 그 테스트가 'forged' 라는 틀린 nonce 를 썼기 때문에
  통과한 것이었다. A7b 이전(134f264)에는 `sys.argv[1]` 의 nonce 로 정확히 위조하는 후보와 `sys.modules['json'].dump` 를
  패치하는 후보가 **passed=True** 였고, 정답 + non-daemon 스레드는 timeout(거짓 실패)이었다 (Fable 재현, 2026-09-13,
  `tests/test_verify_probe8.py` 로 이 세션에서도 3/8 실패 재현). A7b: nonce·경로를 stdin 으로, 기록기 사전 바인딩, 종료 시 os._exit.
- 종료 코드·stdout 은 통과 신호가 아니다. 하네스의 result.json(nonce) 만 본다. `passed=True` 는 level=functional 뿐이라
  **공개 테스트가 없는 과제(현재 G1 러너, `tests: None`)에서는 validator 판정이 항상 `no_tests`/passed=False** 다 —
  doctest 추출(2주차 첫 작업)이 전제인 이유.
- subprocess 모드는 같은 OS 사용자 권한, 파일시스템·네트워크 격리 없음, CPU/메모리 제한 없음(타임아웃만).
  argv/env 를 읽어 nonce 를 위조하는 고의적 후보는 범위 밖. `HARMONET_SANDBOX=docker` 는 python:3.11-slim,
  `--network none`; Docker 없으면 RuntimeError. Docker 모드는 아직 실측 실행하지 않음(이미지 pull 필요).
- v2 의 정적 검사(`_cheap_validate`)도 level=static 이라 passed=False. v2 가 "accepted" 로 삼는 기준은 outcome 뿐.

## A7c 공개/히든 분리 · EvalPlus 확인
- HumanEval: 공개 = docstring `>>>` doctest → `spec["tests"]` (첫 20개 과제 모두 1~3개 존재), 히든 = `check(entry_point)` 프로그램 1건.
- MBPP: `test_list` 가 프롬프트에 노출 → **히든 없음**. 러너는 대조·기록을 위해 같은 test_list 로 채점하되 `hidden_exposed=True` 로 표시.
  히든 점수로 인용 금지. 공개 검증용으로만.
- EvalPlus 0.3.1 (`pip download` 로 휠만 확인, 미설치): 과제마다 `base_input`(원본 테스트 입력) 과 `plus_input`(추가 생성 입력) 이
  **분리**돼 있고 기대 출력은 저장돼 있지 않아 `canonical_solution` 실행으로 얻는다(evalplus 자체 평가기가 수행). 따라서 plus_input 은
  프롬프트에 없는 히든 테스트로 채택 가능. 비용: `pip install evalplus`(numpy·tqdm·wget 등), HumanEval+ v0.1.10 / MBPP+ v0.2.0 캐시 다운로드(수 MB),
  기대 출력 생성용 canonical 실행 1회. **보류 사유: 이번 작업 범위를 좁히기 위해.** LCB 가 모든 층에서 부적격일 때의 예정된 대안. 채택은 승인 후.
- 재채점 대조: 거짓 통과 0/360. v1 산출물은 120/120 `heuristic` 추출(코드 블록 없이 출력) — 채점엔 문제 없었으나 2주차 arm 에서는 fenced 를 요구할 것.

## 검토 오류 기록 (2026-09-13, 코덱스 지적으로 발견)
| 누가 | 무엇을 틀렸나 | 근거 파일 |
|---|---|---|
| Fable | C2 §0 "최선 고정 = REDEREF 사후분포가 수렴하는 정책" 주장 — REDEREF 원문을 확인하지 않고 씀. REDEREF 는 질의 유사도·시간 감쇠로 사전분포를 두고 판정 결과로 재라우팅·종료한다 | `docs/week2_design_draft.md` §0 (C3 에서 정정), `docs/related_work_week1.md` REDEREF 행 |
| Fable | 교수님 문서에서 SWE 11/30 을 HarmoNet 수치로 오기 — 실제는 single_validate(single + apply-check 수리) | `evidence/swe_fair/haiku_0_30_4k_nohints/README.md` |
| Fable | v1 토큰 434 를 2차 통과율 옆에 배치해 같은 조건처럼 읽히게 함 | `evidence/g1_fair/rerun/README.md` |
| Fable | "힌트 빼면 25%" 를 인과로 서술 — README 는 hints 유무를 통제한 비교가 아님(모델·max_tokens 도 함께 바뀜) | `evidence/swe_fair/haiku_0_30_4k_nohints/README.md` |
| Claude Code | A7 보고 "argv 위조도 nonce 불일치로 aborted" — 테스트가 'forged' 라는 틀린 nonce 를 써서 통과한 것. 실제로는 argv 를 읽는 후보가 passed=True 였음 | `tests/test_verify_probe8.py` (A7b), 이 파일 A7 항목 |
| Claude Code | A7 에서 verify 함수만 고치고 러너(`external_g1.py`)의 채점 호출처는 연결하지 않아 옛 종료 코드 채점기가 그대로 쓰임 | A7c 커밋 `d7f429a` 이전의 `benchmark/external_g1.py:evaluate_code` |
| Fable | stdio 하네스 규칙 "출력 완료 시점 기준 pass + kill" — 정답 출력 후 RuntimeError/무한루프가 pass 로 판정됨 (코덱스 재현). A0c 에서 rc==0 ∧ 정상 종료 규칙으로 교체 | `harmonet/verify.py` stdio docstring, `tests/test_verify_stdio_adversarial.py` |
| Fable | C3 §4 "참값은 보수적 gap 과 낙관적 gap 사이" — 근거 없는 괄호 주장. A0c 에서 삭제, 판정은 통과/미확인 둘로 | `docs/week2_design_draft.md` §4 |
| Claude Code | HumanEval+ 제외 사유를 "천장(96.3%)"으로 씀 — 96.3% 는 HumanEval 결과이고 HumanEval+ 제외 사유는 164개 표본 조건 미달 | `evidence/week2/pool_probe.md` (A0c 정정) |
| Claude Code | 노출 가드가 True 로 해석되지 않는 값을 전부 False 로 취급 — `{"hidden_exposed": "unknown"}` 이 히든 1.0 (코덱스 재현). A0c 에서 명시적 False 만 허용 | `benchmark/hidden_guard.py`, `tests/test_hidden_guard.py` |
| Fable | B 단독 상한 70% 를 유도 없이 A 창을 복사해 사전 등록함 (유도값은 80%: B 실패율 ≥ 2×MDE). 결과 뒤 문턱을 옮기지 않은 것은 맞으나 유래를 처음부터 적었어야 함 (2026-09-14, 코덱스 지적) | `evidence/week2/pool_probe.md` 프로브 4, `docs/week2_review_draft.md` §3-2 |
| Fable | 재검토 초안에서 "가시 신호가 약하다" 단정 — 조건부 표(가시 실패→히든 실패 A 9/12, B 5/6)를 보면 실패 예측력은 있음. D4 에서 표로 대체 | `docs/week2_review_draft.md` §3-4 |
| Fable | "규칙 변경 시 새 프로브 60 필수" — 과함. 프로브는 성공률 추정용이고 새로 추정할 양이 없으면 기존 60 은 탐색 자료로 두고 확인 자료에서 평가하면 됨 | `docs/week2_review_draft.md` §4 |
| Fable | BCB 채점 결과의 n_run 이 "모듈 호출 수"(항상 1)인 것을 확인하지 않고 실행 수처럼 읽음 | `evidence/week2/bcb_source.md`, D2 이전 `harmonet/bcb_harness.py` |
| Claude Code | BCB 하네스 n_run = 테스트 모듈 호출 수. 공식 untrusted_check 는 실행된 테스트 수를 검사하지 않으므로 TestCase.run 을 no-op 으로 바꾼 후보가 pass (코덱스 지적, D2 에서 재현·수정: expected_tests 클린 프로세스 계수 + testsRun 검사 + 사전 바인딩) | `harmonet/bcb_check.py`, `tests/test_bcb_adversarial.py` |
| Claude Code | 누적 예산을 강제하지 않음 — 사전 등록 "상한 $1" 이 코드 어디에도 없었고 사후 합산만 함. D1 에서 원장·예약·중단 | `harmonet/budget.py`, `benchmark/runloop.py` |
| Claude Code | 채점 인프라 장애(docker 데몬·이미지) 시에도 다음 모델 호출을 계속함 — 후보 원인 aborted 와 구분 없음. D1 에서 infra 플래그 + 사전 점검 + 즉시 중단 | `harmonet/verify.py` `_run_bcb_harness`, `benchmark/runloop.py` |
| Claude Code | 타임아웃 시 docker CLI 만 죽이고 컨테이너는 정리하지 않음 (Windows 에서는 CLI kill 로 파이프도 안 닫혀 컨테이너 종료까지 대기). D1 에서 named container + docker kill + rm -f | `harmonet/verify.py`, `tests/test_budget_runloop.py` |

**패턴 (세 번째, 코덱스 지적으로 발견): "이름을 보고 구현을 읽지 않음."** A1 (validator 이름만 보고 LLM 호출 여부 미확인), A7 (하네스 종료 코드를
통과 신호로 믿음), D2 (`n_run` 이라는 이름을 실행 수로 믿고 공식 채점기가 실행 수를 세지 않는다는 것을 읽지 않음). 다음 인프라 항목부터는
"이 이름의 값이 실제로 무엇을 세는가" 를 테스트로 먼저 고정한다.

## Week2-A0 LiveCodeBench 로더·stdio 하네스
- 데이터는 HF `livecodebench/code_generation_lite` revision `0fe84c3912ea0c4d4a78037083943e8f0c4dd505` 의 jsonl 을 직접 받는다
  (로딩 스크립트/`trust_remote_code` 불필요). `private_test_cases` 는 base64→zlib→**pickle**(JSON 문자열): 공식 출처 + 고정 revision 파일만
  역직렬화한다. 다른 출처 파일은 넣지 않는다 (`benchmark/lcb.py` docstring).
- stdin 문제는 전부 atcoder, functional 문제는 전부 leetcode. test5+test6(2024-09~2025-04) stdin 217개; **2025-01-01 이후 stdin 은 112개(medium 26)**.
  사전 등록 필터(medium·2025+)로는 프로브 60 도 확인용 ≥200 도 확보 불가 → 프로브 미실행 (pool_probe.md).
- 하네스 메모리 상한은 Windows 에서 미적용(`mem_limit=not_applied(windows)` 로 기록). POSIX 는 RLIMIT_AS 2GiB.
- 비교 규칙은 공식 `grade_stdio` 를 옮김: 줄 수 일치 필수, 줄 단위 strip, 정확 일치 아니면 양쪽 Decimal 리스트 일치. 비수치 줄은 대소문자 구분.
- 원인 불명 1회 관찰: Week2-A0 커밋 직후 콘솔에 `python.exe: can't open file '<repo>\candidate.py'` 가 한 줄 찍힘 (cwd=저장소 루트에서
  `python -I candidate.py` 가 실행된 흔적). 재실행·잔여 프로세스 확인으로 재현 안 됨. 하네스는 후보를 tmp/run 에서만 띄우므로 경로가 설명되지 않는다.
  다시 나타나면 하네스 launch 를 로그로 남겨 추적.

## Week2-B0 MBPP+ 준비·프로브 (2026-09-14)
- **정답 출력 크기 폭발**: Mbpp/255 의 canonical 출력 repr 이 1.29GB(조합 열거), Mbpp/630 이 11MB. JSON 스펙에 못 넣어 두 과제 제외(상한 1MB).
  첫 탐색 스크립트가 이 출력을 eval 로 복원하다 18GB 를 먹어 프로세스를 강제 종료했다. 공식 evalplus 는 이걸 pickle 캐시로 메모리에 들고 있다.
- **plus 입력 0개 과제**: Mbpp/793 은 plus_input 이 비어 있어 plus_only_pass 를 정의할 수 없다 — 풀에서 제외. 정답 전수 확인에서 드러남(375/376).
- **repr 왕복**: 집합의 repr 순서·복소수 `-0-1j` 는 문자열은 달라도 값·타입이 같다. 왕복 검증을 문자열 비교에서 값+타입 비교로 바꿈.
- **공식 채점기는 Windows 에서 안 돈다**: `time_limit` 이 SIGALRM, `reliability_guard` 가 resource 모듈. 동등성 오라클은 이 둘을 비활성으로
  두므로 우리가 말할 수 있는 건 "비교 판정이 검사한 17개 사례에서 공식과 일치" 까지다. 시간 제한·격리 동등성은 주장하지 않는다 (B2 1-2 정정).
- **atol 상태 전이**: 공식 루프에서 `atol` 이 케이스 사이에 바뀐다(float 기대값 이후 1e-6 유지). 순서를 바꾸면 판정이 달라지는 케이스를
  테스트로 고정(`atol_state_*`). 스펙 생성 시 케이스별 atol 을 미리 계산.
- **가격표 별칭 불일치**: API 응답 `model` 이 `claude-haiku-4-5-20251001` 이라 `claude-haiku-4-5` 항목과 안 맞아 프로브가 cost_usd=None 으로 돌았다
  (경고는 찍혔음). 날짜 접미사를 떼서 조회하도록 수정(90498eb). HumanEval 프로브 때는 토큰으로 손계산했었다.
- **프로브 결과 85%** → [30,70] 밖 → unconfirmed. `evidence/week2/pool_probe.md` 프로브 3.

## Week2-B2 / C0 (2026-09-14)
- **파이프 교착**: 과제별 워커가 결과 JSON(최대 ~800KB)을 stdout 으로 내보내자 64KB 파이프가 차서 자식이 막히고 부모는 종료를 기다리다 30s 에 kill —
  전 과제가 "시간 초과" 로 제외될 뻔했다. 결과·stderr 를 파일로 바꿔 해결. Windows venv 의 python.exe 는 런처라 실제 인터프리터가 자식 프로세스 →
  RSS 감시·kill 은 psutil 트리 단위로.
- **Mbpp/255** 는 이제 메모리 상한(2.49GB > 2GiB)으로 제외된다 — 이전 "repr 1.29GB" 와 같은 과제, 사유만 바뀜. 스펙 재생성 후 프로브·확인 ID 불변.
- **BCB 공식 이미지**는 ENTRYPOINT 가 `bigcodebench.evaluate` 라 `--entrypoint python3` 로 덮어야 우리 하네스가 돈다. 15.1GB.
- **BCB doctest 는 절반 이상이 예시용**(가상 경로·파일): 정적 스크린 통과 637 중 canonical 로 실제 통과하는 건 412. 정적 스크린은 "seed/random/Axes" 로
  384개를 걸렀는데, 그중엔 `isinstance(result, float)` 처럼 결정적인 예제도 있었을 것 — 보수적으로 잃은 셈.
- **B 상한 조건**: 사전 등록의 B ≤ 70% 를 sonnet-4-6 이 75% 로 넘겼다. A 는 창 안. 규칙대로 unconfirmed, 재검토 초안(`docs/week2_review_draft.md`)만.

## Week2-D (2026-09-14) 예상과 달랐던 것
- **k=3 교차 적합 gap 은 참 상호작용을 거의 다 깎아 잰다** (`evidence/week2/power_prelim.md` §2): 합성에서 참 상호작용 0.3(oracle gap 17pp)이어도
  교차 적합 추정 대상은 ≈ 0. 6 arm 중 과제별 최선을 반복 2개로 고르는 선택이 잡음이라 최선 고정(전 과제 합산)에 진다. 10pp 문턱을 이 통계량에
  걸면 참 상호작용 ≈ 0.5 이상이어야 통과. 설계 §4-3 경고의 실제 크기. 판단 대상(문턱을 거는 추정량·k·후보 arm 수).
- 합성 검증 (b) 는 "oracle gap 포함" 으로 두면 0/5 였고, 추정 대상을 교차 적합 통계량의 기대값(몬테카를로)으로 정의해야 20/20 이 된다 — 부트스트랩이
  덮는 것은 그 기대값이지 oracle 이 아니다.
- 이미지 안 Python 3.10: 스레드에서 fork 한 자식은 정상 종료해도 exitcode 1. `reliability_guard` 아래서는 자식이 죽어도 join(timeout) 이 안 깨어난다
  (손자가 sentinel 보유). 공식 채점기는 둘 다 안 보므로 드러나지 않던 문제.
- Windows: docker CLI 프로세스를 죽여도 파이프가 안 닫혀 컨테이너가 끝날 때까지 대기 — 타임아웃 처리는 `docker kill <name>`.
- 정적 필터 v1 의 `open\(\b` 는 아무것도 못 잡는 패턴이었다(괄호 뒤 `\b`). 테스트 없이 정규식을 믿은 것.
- D2 기대 테스트 수 계수: test 모듈 3개(227·594·721)는 후보 없이 로드되지 않는다(클래스 정의 시점에 task_func 참조). 실행 수를 검증할 수
  없으므로 채점 불가로 제외 — 공식 채점기라면 통과시켰을 과제.
- atexit 은 multiprocessing 자식(os._exit 종료)에서 실행되지 않아 "정답 뒤 atexit os._exit" 은 공격 경로가 아니었다 — 테스트에서 제외.

## Week2-F1 정정 (2026-09-15)
- D5 보고의 "mock 스모크 3 과제 × 6 arm: 18 traces validate … eval:hidden 0" 은 맞지만, **채점은 한 건도 컨테이너에서 돌지 않았다**: MockLLM 이 코드가 아닌
  문장을 내서 18/18 이 정적 `error`(AST 단계, exec_count 0)였다. "18행 공식 이미지에서 돌았다" 는 D3 문서 문장은 틀렸고 정정했다.
  F1 에서 유효 코드 시나리오 mock(정답/오답/근접오답)으로 3 과제 × 6 arm × k=2 = 36 행을 실제 Docker 에서 돌려 기대 히든 결과와 36/36 일치.
