# HarmoNet 보안·신뢰성·검증성 감사 보고서

감사일: 2026-09-12
범위: `harmonet/`, 벤치마크, 테스트, Docker/Compose 배포 설정 및 저장된 실험 근거. 코드 변경은 하지 않았다.

## 요약

이 저장소는 README가 말하듯 연구 프로토타입이며, 현재 상태를 멀티테넌트·분산·프로덕션 런타임으로 운영하면 안 된다. 가장 큰 문제는 **신뢰되지 않은 Redis seed가 LLM 실행 입력과 결과 저장소를 동시에 지배한다는 것**이다. Compose 기본값은 그 Redis와 관측 UI를 호스트 포트로 공개하고, 인증·권한·테넌트 격리를 제공하지 않는다.

또한 Compose가 설정하는 Redis 환경변수와 런타임이 읽는 환경변수가 달라 기본 배포에서 공유 저장소가 조용히 로컬 폴백으로 전환된다. 즉, health check는 통과해도 이 프로젝트의 핵심인 분산 필드/선점은 동작하지 않는다. 벤치마크 근거도 이미 저장소 스스로 인정하듯 HarmoNet 고유 구조의 효과를 보이지 못했으며, 기본 어댑터는 일부 조건에서 공명 경로 대신 직접 repair LLM 호출로 답을 만든다.

검증 결과:

- `pytest -q`: **167 passed**. 단, Redis/Compose/실제 LLM 보안 경계를 검증하지 않는다.
- `ruff check harmonet tests`: **18 errors**. CI는 lint를 실행하지 않는다.
- 재현: `NaN` payload/energy seed를 투하하면 필드에 `NaN`이 남는다.
- 재현: 명시한 `grid_position=0`이 무시되고 해시 기반 위치로 바뀐다.
- 재현: FAISS 경로는 `min_seed_energy`를 무시해 브루트포스 경로와 다른 seed를 실행 후보로 만든다.
- 현재 로컬 의존성 충돌로 sentence-transformers가 실패했고, 경고만 남긴 뒤 해시 임베딩으로 폴백했다. 이 상태의 2-tick HarmoNet 어댑터는 `tasks_completed=0`인데 repair 호출로 최종 출력을 만들었다.

## P0 — 즉시 차단할 항목

### SEC-01: 공개 가능한 무인증 Redis가 seed 실행·결과 탈취 제어면이 된다

근거: [docker-compose.yml](docker-compose.yml) 50-65행은 Redis `6379:6379`를 publish하고 인증, ACL, TLS, 명시적 localhost bind를 두지 않는다. [store.py](harmonet/store.py) 155-184행은 이 Redis의 모든 레코드를 신뢰하여 역직렬화한다. [agent.py](harmonet/agent.py) 643-655행은 `seed.rule_description`을 LLM prompt로 보낸다. Builder는 결과 전체를 `metadata.full_output`로 같은 Redis에 저장한다([agent.py](harmonet/agent.py) 741-772행).

영향: 포트에 도달하는 주체는 다른 작업의 결과를 읽거나 삭제하고, 임의 seed를 넣어 LLM 호출·비용·작업 내용을 조작할 수 있다. 이 코드에 자동 shell 실행은 없지만, downstream `task_executor`가 작업 텍스트를 실행하는 배포라면 영향은 더 커진다. seed creator ID를 위조해 agent/Prometheus label을 무제한 생성할 수도 있다.

조치: Redis 포트를 기본 비공개로 하고 app network에만 연결한다. Redis ACL/비밀·TLS(필요한 네트워크 경계에서)를 설정하고, seed에 발행자 인증·서명·tenant/session ID·스키마 검증·크기 제한을 적용한다. raw output은 공유 seed metadata에 저장하지 말고 권한 검사되는 별도 artifact store에 암호화해 보관한다.

### SEC-02: 기본 Grafana 비밀번호와 관리 포트 공개

근거: [docker-compose.yml](docker-compose.yml) 87-100행은 `3001:3000`을 publish하고 `GRAFANA_PASSWORD` 미설정 시 `harmonet`을 admin 비밀번호로 사용한다. Prometheus와 Jaeger 포트도 각각 9090, 16686/4317로 publish된다(67-112행).

영향: 호스트 네트워크에서 접근 가능한 경우 관측 데이터·서비스 정보가 노출되고 Grafana 관리 계정 탈취 위험이 있다.

조치: 기본 비밀번호를 제거하고 배포 시 secrets로 필수 주입한다. 운영 기본값에서는 관리 포트를 publish하지 말고 reverse proxy/VPN/allowlist 뒤에 둔다.

## P1 — 출시 전에 해결할 항목

### REL-01: Compose 기본 배포는 Redis를 쓰지 않는데 준비 상태는 정상이다

근거: Compose와 Dockerfile은 `REDIS_HOST`/`REDIS_PORT`를 설정한다([docker-compose.yml](docker-compose.yml) 20-22행, [Dockerfile](Dockerfile) 33-40행). 실제 store는 `HARMONET_REDIS_HOST`/`HARMONET_REDIS_PORT`만 읽고 기본값 `127.0.0.1:6379`을 쓴다([store.py](harmonet/store.py) 73-75행). health endpoint만 전자의 값을 읽고([health.py](harmonet/health.py) 52-65행), `/readyz`는 의존성이 없어도 항상 200/ready=true다(99-123행).

영향: 같은 Compose stack에서 health는 Redis를 발견하지만 HarmoNet은 로컬 in-memory fallback으로 작동한다. 다중 프로세스 선점, 공유 field, seed 동기화가 모두 깨진다.

조치: 환경변수 하나(`REDIS_URL` 권장)로 통일하고 실제 Redis container를 포함한 E2E 테스트를 만든다. 공유 Redis가 필수인 모드는 fallback이면 readiness 503을 반환해야 한다.

### SEC-03: seed 역직렬화와 필드 투하에 스키마·차원·유한성·용량 검증이 없다

근거: [store.py](harmonet/store.py) 47-67행은 JSON/base64를 제한 없이 ndarray로 만든다. `dim` 인자는 [store.py](harmonet/store.py) 171-188행에서 쓰이지 않는다. [field.py](harmonet/field.py) 116-145행은 position, vector shape, `NaN`/`inf`, 음수/비정상 TTL을 검증하지 않고 field에 더한다.

재현: `payload=[NaN,...]`, `energy=NaN`으로 투하하면 `seed.energy < H_DATA`는 false이고 `np.clip`도 NaN을 고치지 않아 field가 NaN으로 오염된다. 또한 차원이 다른 frequency는 FAISS/`np.dot` 중 예외를 유발해 scan loop를 중단시킬 수 있다.

조치: Pydantic/dataclass validator 또는 엄격한 schema를 두고 ID 길이, UTF-8 문자열/metadata 크기, 정확한 `(dim,) float32`, `np.isfinite`, `0 < ttl <= 상한`, `H_DATA <= energy <= 상한`, grid 범위를 검증한다. 잘못된 remote record는 한 건씩 격리·계수화하고 전체 registry를 local fallback으로 바꾸지 않는다.

### SEC-04: 인증 설정처럼 보이는 `HARMONET_API_TOKEN`은 전혀 집행되지 않는다

근거: [.env.example](.env.example) 18행에는 `HARMONET_API_TOKEN`이 있지만 그 사용처는 없다. [health.py](harmonet/health.py) 90-156행은 `/healthz`, `/readyz`, `/metrics`, `/status`, `/docs`를 무인증으로 제공한다.

영향: 설정했다고 믿어도 service fingerprint, Redis host/오류, Python/platform 및 metric labels가 노출된다. `/status`는 외부 감시 대상이 아닌 상세 상태 endpoint여야 한다.

조치: public health와 authenticated admin/status/metrics를 분리한다. 필요 없다면 예제 토큰 변수를 삭제하고 네트워크 접근만 허용된 scrape identity에 `/metrics`를 노출한다.

### REL-02: 분산 field는 last-writer-wins이며 seed 원자성도 없다

근거: [field.py](harmonet/field.py) 257-279행은 Redis에서 field 전체를 읽어 계산한 뒤 전체 bytes를 다시 쓴다. [store.py](harmonet/store.py) 121-153행은 data와 shape를 별도 `SET` 두 번으로 쓴다. deposit도 local field 갱신 후 전체 state를 저장한다([field.py](harmonet/field.py) 130-142행).

영향: 두 프로세스가 동시에 seed를 deposit/propagate하면 마지막 writer가 다른 writer의 변화와 seed 효과를 덮어쓴다. data/shape 사이에 reader가 끼면 reshape 실패로 조용한 local fallback도 가능하다. "분산" 결과가 재현 불가능하다.

조치: field를 key별 atomic vector accumulator로 재설계하거나 Lua transaction/WATCH+version/CAS를 사용한다. field bytes와 shape는 한 versioned payload에 저장하며, session namespace와 optimistic retry를 둔다.

### REL-03: 선점 lease가 작업 시간과 seed TTL에 맞지 않아 중복 실행/영구 건너뛰기가 난다

근거: [field.py](harmonet/field.py) 190-209행은 120초 lease를 사용한다. seed 기본 TTL은 300초([field.py](harmonet/field.py) 20-35행), LLM timeout은 120초·300초까지 가능하다([llm.py](harmonet/llm.py) 240-263행, 550-565행). claim 이후 TDA가 실패하면 처리 완료/해제 없이 `continue`한다([agent.py](harmonet/agent.py) 633-641행).

영향: 긴 작업은 lease가 만료되어 다른 agent가 중복 실행한다. 반대로 실패한 claim은 재시도 정책 없이 120초 동안 작업을 막는다. Redis 오류 시에는 "liveness"를 이유로 누구나 claim 성공 처리한다([store.py](harmonet/store.py) 215-223행).

조치: idempotency key와 상태 machine(pending/leased/completed/failed)을 만들고 owner-token 기반 lease renewal/release와 bounded retry/DLQ를 구현한다. Redis 오류에는 fail-open이 아니라 명시적 degraded queue 정책을 쓴다.

### REL-04: TDA 검증은 candidate를 검증하지 않으며 실패 시 실행을 허용한다

근거: [agent.py](harmonet/agent.py) 432-447행은 scan 전후의 전체 field snapshot을 저장하고, 각 event에는 동일한 snapshot을 재사용한다. candidate 실행/feedback은 그 뒤에 발생한다. 변화가 없으면 validation은 `True`를 반환하고([resonance.py](harmonet/resonance.py) 384-387행), SciPy와 fallback 모두 실패해도 `True`를 반환한다(389-396행). random subsampling/noise도 결과를 비결정적으로 만든다(409-424행).

영향: "유효 공명"이라는 safety/quality gate는 no-evidence와 analysis failure에서 통과한다. 전역 field 변화는 특정 seed의 품질 또는 task correctness 증거가 아니다.

조치: TDA를 실행 인가 수단으로 쓰지 말고 관찰적 신호로 강등하거나, 명시적인 candidate/task 검증(테스트, schema, policy evaluator)으로 바꾼다. 판단 실패는 fail-closed 또는 retry로 처리하고 seed별 causal snapshot과 결정론적 RNG를 사용한다.

### REL-05: Builder→Validator feedback은 실제 결과를 검증하지 않고 "passed"를 만들어 낸다

근거: Builder는 `full_output`을 metadata에 저장하지만([agent.py](harmonet/agent.py) 741-756행), decoder는 metadata를 읽지 않고 `rule_description`만 반환한다(150-155행). Validator가 받는 것은 특정 FastAPI JWT 문구뿐이고, 이후 실제 검증 결과와 무관하게 "Implementation passed OWASP validation" seed를 생성한다(758-772행).

영향: validator가 builder 산출물을 전혀 검토하지 못한다. 성공/보안 통과 상태는 false positive이며, 민감한 원문은 Redis에 불필요하게 복제된다.

조치: immutable artifact ID와 access-controlled artifact store를 전달하고, validator prompt에 해당 artifact를 제한된 길이/형식으로 명시적으로 넣는다. PASS는 정책·테스트 증거와 연결하고 FAILED/UNKNOWN 상태를 보존한다.

### EVAL-01: 기본 벤치마크가 HarmoNet 구조 효과를 과대평가할 수 있다

근거: [agents_harmonet.py](benchmark/agents_harmonet.py) 177-194행은 공명 결과가 없거나 keyword가 모자라면 직접 LLM repair를 호출한다. 현재 환경에서 mock으로 2 tick을 실행한 결과는 `tasks_completed=0`, `seeds_received=0`, `repair_used=True`였는데 최종 output은 repair 호출이 만들었다. METER는 Mock async가 wrapped sync `generate()`를 다시 호출해 한 실제 호출을 2 calls로 기록한다([llm.py](harmonet/llm.py) 177-181, 488-513행).

또한 v2 adapter는 실제 DataUniverse/agent runtime이 아니라 별도의 builder/validator/cheap-validation 파이프라인이다([agents_harmonet_v2.py](benchmark/agents_harmonet_v2.py) 153-257행). 따라서 v2 수치를 runtime의 resonance/field 결과로 부를 수 없다.

저장소의 최신 실험도 이 점을 지지한다. [evidence/swe_fair/README.md](evidence/swe_fair/README.md) 65-73행은 single+repair가 14/30, harmonet+repair가 11/30이며 HarmoNet 기여가 없다고 결론낸다. [evidence/g1_fair/COMPARISON.md](evidence/g1_fair/COMPARISON.md) 14-16행도 single-call이 v1/v2보다 토큰과 정확도에서 같거나 낫다고 명시한다.

조치: runtime benchmark와 v2 policy benchmark를 분리해 이름 붙인다. seed pipeline, direct repair, fallback 각각의 호출·토큰·성공률을 별도 계측하고, single-call과 동일 system prompt/context/budget의 paired ablation을 주 결과로 둔다. Mock meter double-count를 고친다.

## P2 — 중요하지만 설계 결정을 요구하는 항목

### COR-01: FAISS와 brute-force가 다른 시스템을 구현한다

- FAISS는 `top_k=10`만 먼저 가져와, 더 가까운 위치의 11번째 이후 적합 seed를 놓친다([resonance.py](harmonet/resonance.py) 177-240행).
- FAISS 경로는 `min_seed_energy`를 검사하지 않지만 brute-force는 검사한다(243-293행). energy 0.02 seed가 FAISS에서는 감지되고 brute-force에서는 제외되는 것을 재현했다.
- field는 순환 경계로 deposit하지만([field.py](harmonet/field.py) 130-135행), distance는 일반 절댓값이다([resonance.py](harmonet/resonance.py) 206-209, 250-253행). grid 0과 마지막 grid는 이웃인데 서로 감지하지 못한다.
- `IndexFlatIP`는 exact brute-force 계열이지 문서가 주장하는 O(log N) index가 아니다([store.py](harmonet/store.py) 240-253행).

조치: 위치 filter를 포함한 후보 검색을 설계하고, 모든 경로에 같은 eligibility predicate를 적용한다. 순환 거리 또는 비순환 공간 중 하나를 선택해 모든 연산에 일관되게 적용한다.

### COR-02: core "semantic" 기능이 무음으로 random-like hash fallback이 될 수 있다

근거: [embed.py](harmonet/embed.py) 60-68, 93-101행은 model load failure를 print 후 MD5 기반 난수 벡터로 바꾼다. 이 함수는 전역 `np.random.seed()`도 변경한다. OpenAI embedding API 오류도 같은 fallback으로 숨긴다(255-291행). embedding 호출의 비용·latency는 usage meter에 없다.

영향: 시스템의 routing이 의미 기반이 아니라 해시 기반이 되고, 전역 RNG 변경은 phase/TDA 재현성까지 흔든다. 사용자는 degraded mode인지 API/status/metric에서 알 수 없다.

조치: production에서 semantic encoder failure는 readiness failure 또는 명시적 opt-in degraded mode로 만든다. `np.random.default_rng(local_seed)`를 사용하고 cache/model init을 lock으로 보호한다. embedding usage/cost/latency를 분리 계측한다.

### COR-03: 기본 위치와 모델 파라미터가 재현성과 이론적 의미를 훼손한다

근거: [agent.py](harmonet/agent.py) 290행의 `grid_position or ...` 때문에 명시적 0이 무시된다(재현: grid 11에서 요청 0 → 실제 8). `hash(agent_id)`는 Python process마다 randomized라 분산 process에서 위치가 달라진다. 모든 domain vector를 정규화한 뒤 norm을 natural frequency로 사용하므로 대부분 agent의 frequency는 1.0이다(273-287, 497-506행). SOC는 실제 위임/재귀 cascade/부하 decay가 없다(158-237행).

조치: `is None` 체크와 stable hash를 사용한다. frequency를 의미 있는 scalar에서 derive하고 seed RNG를 기록한다. SOC를 실 workload scheduler로 구현하지 않는다면 연구 용어·지표에서 제외한다.

### OPS-01: 관측성과 alert는 선언만 되고 거의 갱신되지 않는다

근거: [metrics.py](harmonet/observability/metrics.py)에는 Redis/LLM/field/claim 지표가 정의되지만, `rg` 결과 사용처는 대부분 정의와 테스트뿐이다. 예를 들어 alerts는 `harmonet_llm_requests_total` 및 `harmonet_redis_operations_total`을 요구한다([prometheus-alerts.yml](deploy/prometheus-alerts.yml) 13-38행)지만 runtime이 이를 increment하지 않는다.

조치: critical path에 metrics/tracing을 실제 삽입하고 integration test에서 series 값 증가와 alert expression을 검증한다. 거짓 "production readiness" alert는 제거하거나 구현한다.

### OPS-02: 상태 보존·테넌트 격리·GC가 없다

근거: 모든 Redis key는 고정 `harmo` prefix다([store.py](harmonet/store.py) 73-77행). seed hash는 Redis TTL을 갖지 않고, crash한 publisher의 record는 임의 process가 나중에 청소할 때까지 남는다. `clear()`는 `KEYS harmonet:*`으로 shared namespace 전체를 scan/delete한다(225-237행).

조치: run/tenant namespace, per-record TTL, bounded queues, Redis SCAN 기반 GC와 role-based delete 권한을 사용한다. benchmark는 task/run별 isolated namespace를 사용한다.

### EVAL-02: 일반 benchmark success/cost/통계는 연구 결론에 부적합하다

근거: [harness.py](benchmark/harness.py) 50-53행은 실행 모델과 무관하게 GPT-4o-mini 가격을 적용한다. 167-181행은 keyword 50% 포함을 success로 삼는다. runtime 과제가 functional correctness를 요구해도 prompt 키워드 반복으로 통과 가능하다. 기존 G1 보고서는 이 한계를 일부 공개했지만, CI의 mock smoke는 실제 quality/공정성 증명이 아니다.

조치: task별 executable evaluator/official harness, paired seeds, confidence interval 및 비용 모델별 실제 가격을 사용한다. token, embedding, storage, retry, queue, validation 비용을 합친 end-to-end 비용을 보고한다.

## P3 — 유지보수·품질 부채

- [requirements*.txt](requirements.txt)은 최소 버전만 있고 lock/SBOM/취약점 스캔이 없다. `pip-audit`은 이 환경에 설치되어 있지 않았다. Docker 이미지는 특정 오래된 관측 이미지 tag를 사용하지만 업데이트·CVE 정책이 없다.
- CI는 unit/import/이미지 build만 하고 lint, dependency audit, Redis Compose E2E, real LLM contract test, auth test, concurrent writer chaos test를 하지 않는다([ci.yml](.github/workflows/ci.yml)).
- `pytest-asyncio` loop-scope deprecation warning이 발생한다. `ruff check harmonet tests`는 18개 오류를 냈다.
- broad `except Exception`이 store/LLM/embedding path에서 정상처럼 fallback하며, 오류 원인·degraded 상태·데이터 손실을 감춘다. 특히 Redis claim 오류의 allow path는 integrity와 상충한다.
- task/seed 일부가 `print`로 로그에 그대로 출력된다([field.py](harmonet/field.py) 147-148행). secret가 포함된 작업이면 로그 노출이 된다. structured logger와 secret redaction 정책을 실제 runtime에 적용해야 한다.
- README의 runtime Docker image test 명령은 runtime target에 pytest가 없어서 그대로는 실패한다([README.md](README.md) 102-107행, [Dockerfile](Dockerfile) 50-56행). dev target을 쓰거나 test image를 문서화해야 한다.

## 권장 우선순위

1. 공개 포트/기본 Grafana password를 제거하고 Redis를 비공개·인증·tenant namespace로 전환한다.
2. seed schema/서명/size/finite validation을 Redis read와 field write 앞에 넣고 malformed record quarantine을 구현한다.
3. Redis config name을 통일하고 Compose E2E에서 실제 shared field/atomic claim을 검증한다.
4. output artifact ACL, owner-token lease state machine, idempotent retry를 설계한다.
5. runtime/benchmark의 direct fallback과 actual field processing을 분리 계측하고 single-call paired ablation을 정식 primary result로 삼는다.
6. degraded embedding mode, observability, lint/dependency audit, concurrency/property tests를 CI gate로 만든다.
