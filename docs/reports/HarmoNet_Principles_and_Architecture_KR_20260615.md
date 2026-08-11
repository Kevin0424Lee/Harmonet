# HarmoNet 원리 및 구조 설명서

작성일: 2026-06-15  
목적: 테스트 결과가 아니라 HarmoNet 자체의 구조, 수식, 동작 원리, 설계 의도를 이해하기 위한 문서

## 1. 한 줄 정의

HarmoNet은 모든 에이전트를 매번 호출하지 않고, 작업을 압축된 seed로 공유 필드에 투하한 뒤, 의미적으로 공명하는 에이전트만 선택적으로 활성화하는 토큰 효율형 멀티에이전트 런타임이다.

조금 더 기술적으로 쓰면 다음과 같다.

```text
HarmoNet = Seed encoding
         + Shared vector field
         + Resonance-based routing
         + Cheap validation
         + Sparse LLM activation
         + Operational fallback layer
```

기존 멀티에이전트 시스템이 "정해진 그래프/대화 순서에 따라 여러 에이전트를 호출"하는 쪽에 가깝다면, HarmoNet은 "작업 신호를 공유 공간에 놓고, 해당 신호와 잘 맞는 에이전트만 반응"하게 만든다.

## 2. 왜 이런 구조가 필요한가

멀티에이전트 시스템의 기본 문제는 비용이다. 여러 에이전트가 같은 작업을 반복해서 읽고, 각자 긴 응답을 생성하고, 다시 중간 조정자가 대화를 정리하면 토큰과 지연이 빠르게 증가한다.

HarmoNet의 설계 목표는 다음이다.

1. 모든 에이전트가 모든 작업에 참여하지 않게 한다.
2. 작업을 그대로 긴 프롬프트로 전달하지 않고 seed라는 압축 단위로 변환한다.
3. 에이전트의 전문 영역과 작업 seed의 의미 벡터가 맞을 때만 실행한다.
4. LLM 호출 전에 가능한 검증은 정적/저비용 방식으로 처리한다.
5. 외부 저장소나 인덱스가 없어도 fallback으로 살아 있게 만든다.

## 3. 전체 구조

![HarmoNet architecture](C:/Users/User/Documents/antigravity/kind-pasteur-harmonet-v2-20260602/output/doc/harmonet_principles_visuals/architecture_runtime_loop.png)

주요 구성요소:

| 구성요소 | 역할 |
|---|---|
| SeedEncoder | 자연어 작업을 frequency/payload/energy/phase를 가진 seed로 변환 |
| DataUniverseField | seed가 투하되는 공유 벡터 필드 |
| ResonanceDetector | 에이전트와 seed의 의미적/위상적 공명 여부 판단 |
| KuraMotoCoupler | 에이전트 간 phase 동기화 모델 |
| HarmoAgent | architect, builder, validator 등 실제 작업 수행자 |
| SOCController | 과부하 시 작업을 이웃 에이전트로 분산 |
| RedisFieldStore | 멀티프로세스 공유 상태 저장 |
| FAISSSeedRegistry | seed similarity search 가속 |
| LLMClient | OpenAI, Anthropic, RunYourAI, Ollama, Mock 백엔드 연결 |

## 4. Seed 모델

HarmoNet에서 작업은 seed로 표현된다.

```text
Seed S = (id, creator, f, p, r, e, theta, t, ttl, metadata)
```

각 항목의 의미:

| 기호 | 코드 필드 | 의미 |
|---|---|---|
| `id` | `id` | seed 고유 식별자 |
| `creator` | `creator_id` | seed를 만든 에이전트 |
| `f` | `frequency` | 작업 도메인 주파수 벡터 |
| `p` | `payload` | 실제 작업 내용의 압축 벡터 |
| `r` | `rule_description` | 사람이 읽을 수 있는 작업 설명 |
| `e` | `energy` | 필드에 미치는 영향 강도 |
| `theta` | `phase` | 생성 시점의 에이전트 phase |
| `t` | `timestamp` | 생성 시각 |
| `ttl` | `ttl_seconds` | seed 생존 시간 |
| `metadata` | `metadata` | 부모 seed, 전체 출력 등 부가 정보 |

Seed를 벡터 필드에 투하할 때 실제로 쓰는 값은 다음이다.

```text
field_vector = payload * energy
```

즉, seed의 payload는 방향이고 energy는 세기다.

## 5. Seed Encoding 원리

작업 설명과 에이전트 도메인 태그는 embedding encoder를 통해 벡터화된다.

도메인 태그가 `tag_1, tag_2, ..., tag_n`일 때 frequency vector는 다음과 같이 만든다.

```text
raw_f = mean(embed(tag_1), embed(tag_2), ..., embed(tag_n))
f = normalize(raw_f)
```

작업 본문은 payload가 된다.

```text
p = normalize(embed(task_description))
```

작업 복잡도는 단어 수 기반 근사값으로 계산된다.

```text
complexity = min(1.0, word_count(task_description) / 50)
energy = 0.3 + 0.7 * complexity
```

해석:

- 짧고 단순한 작업도 최소 energy 0.3은 갖는다.
- 길고 복잡한 작업은 energy가 1.0에 가까워진다.
- energy가 너무 낮으면 field에 투하하지 않는다.

최소 energy 기준은 다음 상수로 표현된다.

```text
H_DATA = 0.01
```

## 6. DataUniverseField 원리

DataUniverseField는 1차원 grid 위에 놓인 벡터 필드다.

```text
Phi in R^(grid_size x dim)
```

예를 들어 `grid_size=16`, `dim=256`이면 필드는 다음 행렬이다.

```text
Phi = [
  phi_0,
  phi_1,
  ...
  phi_15
]

phi_i in R^256
```

### 6.1 Seed 투하

seed가 위치 `x`에 투하되면, 해당 위치와 주변 위치에 Gaussian 형태로 영향을 준다.

```text
for k in (-2, -1, 0, 1, 2):
    Phi[x + k] += e * p * exp(-0.5 * k^2)
```

여기서 `x + k`는 circular boundary를 사용한다. 즉, grid 끝을 넘어가면 반대쪽으로 이어진다.

해석:

- seed는 한 점에만 영향을 주지 않고 근처에도 번진다.
- 가까울수록 영향이 크고, 멀수록 `exp(-0.5*k^2)`로 감소한다.
- 이 구조 때문에 유사한 위치에 놓인 seed들이 국소적 cluster를 만들 수 있다.

### 6.2 필드 전파

필드는 매 tick마다 diffusion-decay equation으로 변한다.

```text
Phi(t + dt) = Phi(t)
            + dt * D * Laplacian(Phi(t))
            - dt * lambda * Phi(t)
```

코드에서:

```text
D = diffusion_rate
lambda = decay_rate
```

1차원 circular Laplacian은 다음과 같다.

```text
Laplacian(Phi_i) = Phi_(i-1) + Phi_(i+1) - 2 * Phi_i
```

해석:

- diffusion 항은 정보가 주변으로 퍼지게 한다.
- decay 항은 오래된 신호가 자연스럽게 사라지게 한다.
- clipping은 수치 폭주를 막는다.

```text
Phi = clip(Phi, -10.0, 10.0)
```

### 6.3 전역 energy

필드 전체의 활성도는 다음으로 측정한다.

```text
E_global = sum(Phi^2)
```

이 값은 현재 시스템에 얼마나 많은 작업 신호가 떠 있는지 보는 지표다.

## 7. Resonance Detector 원리

각 에이전트는 자기 도메인 벡터 `omega`를 가진다.

```text
omega_agent = normalize(domain_vector)
```

seed의 frequency vector를 `f_seed`라고 할 때 cosine similarity는 다음이다.

```text
sim = dot(omega_agent, normalize(f_seed))
```

기본 공명 조건:

```text
sim >= delta
```

여기서 `delta`는 resonance threshold다.

### 7.1 Phase coherence

HarmoNet은 단순 semantic similarity만 보지 않는다. 에이전트 phase와 seed phase의 차이도 고려한다.

```text
dtheta = abs(theta_agent - theta_seed) mod 2*pi
phase_diff = min(dtheta, 2*pi - dtheta)
coherence = max(0, cos(phase_diff))
```

coherence는 phase가 가까우면 크고, 멀면 작다.

실제 strength 계산에서는 coherence가 너무 낮아도 완전히 0으로 죽이지 않도록 하한을 둔다.

```text
effective_coherence = max(0.2, coherence)
```

### 7.2 거리 감쇠

field grid에서 seed와 agent가 멀리 떨어져 있으면 공명 강도를 낮춘다.

```text
distance_decay = exp(-0.1 * distance)
```

최종 resonance strength:

```text
strength = sim * effective_coherence * exp(-0.1 * distance)
```

해석:

- 의미가 맞아야 한다.
- phase가 맞으면 더 강해진다.
- 공간적으로 가까우면 더 강해진다.

## 8. Adaptive Delta

공명 threshold `delta`는 고정값으로만 두면 문제가 생긴다.

- 너무 낮으면 너무 많은 에이전트가 반응한다.
- 너무 높으면 아무도 반응하지 않는다.

그래서 최근 scan 결과를 보고 threshold를 조금씩 조정한다.

```text
resonance_rate = resonance_count / candidate_count
```

조정 규칙:

```text
if resonance_rate > 0.5:
    delta = min(delta_max, delta + 0.02)

if resonance_rate < 0.05 and p70_similarity < delta - 0.1:
    delta = max(delta_min, delta - 0.02)
```

범위:

```text
delta_min = 0.05
delta_max = 0.95
```

이 구조는 운영체제의 adaptive scheduling과 비슷하다. 과도한 wake-up을 막고, 반대로 starvation도 줄인다.

## 9. Kuramoto Coupler

Kuramoto model은 여러 oscillator가 서로 동기화되는 현상을 설명하는 모델이다. HarmoNet에서는 각 에이전트를 oscillator처럼 보고 phase를 갱신한다.

기본 식:

```text
dtheta_i/dt = omega_i + (K / N) * sum_j sin(theta_j - theta_i)
```

여기서:

| 기호 | 의미 |
|---|---|
| `theta_i` | 에이전트 i의 phase |
| `omega_i` | 에이전트 i의 natural frequency |
| `K` | coupling strength |
| `N` | 에이전트 수 |

동기화 정도는 order parameter로 표현된다.

```text
r * exp(i * psi) = (1 / N) * sum_j exp(i * theta_j)
```

코드에서는 `r`에 따라 coupling strength를 조정한다.

```text
K = base_K * (1.5 - r)
```

해석:

- 이미 너무 동기화되어 있으면 coupling을 낮춘다.
- 덜 동기화되어 있으면 coupling을 높인다.
- 모든 에이전트가 한 방향으로 과도하게 몰리는 것을 완화한다.

계산 최적화:

```text
sum_j sin(theta_j - theta_i)
```

를 직접 O(N^2)로 계산하지 않고 order parameter를 이용해 O(N)으로 줄인다.

```text
coupling_sum_i = N * r * sin(psi - theta_i)
```

## 10. TDA 기반 공명 검증

ResonanceDetector는 공명이 감지된 뒤 field 변화가 실제 구조적 변화인지 확인하려고 TDA를 사용한다.

먼저 field 변화량을 본다.

```text
energy_change = norm(after_snapshot - before_snapshot)
```

변화가 거의 없으면 TDA를 생략한다.

```text
if energy_change < 1e-6:
    skip TDA
```

SciPy가 가능하면 single linkage clustering을 사용해 Betti-0 persistent homology를 근사한다.

```text
Z_before = linkage(before, method="single", metric="euclidean")
Z_after  = linkage(after,  method="single", metric="euclidean")
```

각 linkage의 merge distance를 death time으로 본다.

```text
deaths_before = sort(Z_before[:, 2])
deaths_after  = sort(Z_after[:, 2])
```

두 persistence diagram의 1-Wasserstein distance를 다음처럼 근사한다.

```text
W = sum(abs(deaths_before - deaths_after))
```

검증 조건:

```text
is_valid = W > 0.05
```

해석:

- field 구조가 충분히 변했으면 실제 공명으로 본다.
- 변화가 너무 작으면 noise로 간주할 수 있다.

## 11. SOC Controller

SOC는 Self-Organized Criticality의 약자다. HarmoNet에서는 에이전트 부하가 특정 threshold를 넘으면 일부 부하를 다른 에이전트로 넘기는 방식으로 사용한다.

부하 기준:

```text
threshold = 0.75
```

에이전트 부하가 threshold를 넘으면 topple이 발생한다.

```text
spill = load(agent) * 0.5
per_neighbor = spill / number_of_neighbors
```

그 다음 이웃 에이전트들에게 부하를 나눈다.

```text
load(neighbor) += per_neighbor
load(agent) -= spill
```

이 구조는 모래더미 모델과 유사하다. 특정 노드가 과부하되면 주변으로 부하가 퍼지고, 시스템 전체가 극단적 집중을 피한다.

이론적으로 cascade size distribution은 power law 형태를 따른다고 볼 수 있다.

```text
P(s) ~ s^(-alpha)
log P(s) = -alpha * log s + C
```

코드는 cascade history가 충분히 쌓이면 log-log regression으로 `alpha`를 근사한다.

## 12. v2 Sparse Scheduler

HarmoNet v2는 기존 field/resonance 구조 위에 더 현실적인 benchmark/runtime adapter를 얹은 것이다.

![HarmoNet v2 sparse scheduler](C:/Users/User/Documents/antigravity/kind-pasteur-harmonet-v2-20260602/output/doc/harmonet_principles_visuals/sparse_scheduler.png)

핵심 아이디어:

```text
LLM을 부르기 전에 싸게 판단할 수 있는 것은 먼저 판단한다.
항상 validator를 부르지 않는다.
항상 repair를 하지 않는다.
작업 종류에 따라 필요한 stage만 실행한다.
```

### 12.1 Task profile

v2는 먼저 작업을 분류한다.

| Profile | 의미 |
|---|---|
| Patch task | unified diff, SWE-bench 계열 |
| Executable code task | HumanEval/MBPP처럼 함수 실행 검증 가능한 작업 |
| Open-ended task | 설계, 리뷰, 설명처럼 정답 실행이 어려운 작업 |

risk는 다음 식으로 시작한다.

```text
risk = min(1.0, 0.25 + 0.18 * max(1, complexity))
```

추가 규칙:

```text
if patch_task:
    risk = max(risk, 0.90)

if open_ended:
    risk = max(risk, 0.72)

if len(prompt) > 6000:
    risk = min(1.0, risk + 0.12)
```

validator 필요 여부:

```text
validator_required = open_ended or (risk >= validator_threshold and not executable_code)
```

repair 허용 여부:

```text
repair_allowed = patch_task or executable_code
```

## 13. Cheap Validation

Cheap validation은 LLM validator 호출 전에 수행하는 정적 검증이다.

### 13.1 Patch task

검증 항목:

```text
1. unified diff가 존재하는가
2. diff --git으로 시작하는가
3. expected marker가 최소한 포함되는가
```

### 13.2 Executable code task

검증 항목:

```text
1. 코드 블록 또는 def/class/import를 추출할 수 있는가
2. ast.parse(code)가 성공하는가
3. required function name이 존재하는가
4. AST 안에 FunctionDef가 실제로 존재하는가
```

### 13.3 Open-ended task

검증 항목:

```text
hit_rate = keyword_hits / keyword_total
ok = hit_rate >= keyword_threshold
```

기본 keyword threshold는 0.50이다.

## 14. 왜 토큰이 줄어드는가

HarmoNet의 토큰 절감은 마법이 아니라 호출 수와 출력 범위를 줄인 결과다.

토큰 비용을 단순화하면 다음과 같다.

```text
total_tokens = sum(prompt_tokens_i + completion_tokens_i)
```

기존 다중 에이전트 방식이 항상 builder, reviewer, planner, critic 등을 모두 호출한다면:

```text
T_traditional = T_planner + T_builder + T_reviewer + T_critic + T_summarizer
```

HarmoNet v2는 많은 작업에서 다음 형태로 끝난다.

```text
T_harmonet = T_builder + optional(T_repair) + optional(T_validator)
```

또한 builder prompt도 짧게 유지한다.

```text
Return only executable Python code.
No prose unless code comments are required.
```

즉, 효율 개선의 본질은 다음이다.

```text
efficiency_gain = fewer_calls + shorter_prompts + shorter_outputs + cheap_static_checks
```

## 15. Redis와 FAISS의 역할

### 15.1 Redis

Redis는 멀티프로세스 환경에서 seed registry와 field state를 공유하기 위해 사용한다.

주요 역할:

```text
1. field binary 저장
2. seed registry 저장
3. seed position 저장
4. claim lock 제공
```

seed claim은 Redis SETNX로 구현된다.

```text
SET key value NX EX ttl
```

의미:

| 옵션 | 의미 |
|---|---|
| `NX` | key가 없을 때만 set |
| `EX` | 일정 시간 후 자동 만료 |

이 구조는 여러 프로세스가 같은 seed를 동시에 처리하는 race condition을 줄인다.

### 15.2 FAISS

FAISS는 seed frequency vector 검색을 빠르게 하기 위해 사용한다.

벡터가 normalize되어 있으면 cosine similarity는 inner product와 같다.

```text
cosine(a, b) = dot(normalize(a), normalize(b))
```

따라서 FAISS `IndexFlatIP`를 사용한다.

```text
search(query=omega_agent, top_k=10, min_similarity=delta)
```

FAISS가 없으면 brute-force scan으로 fallback한다.

## 16. 운영 엔드포인트

HarmoNet은 서비스 상태 확인을 위해 health server를 제공한다.

| Endpoint | 의미 |
|---|---|
| `/healthz` | 프로세스가 살아 있는지 확인 |
| `/readyz` | Redis, FAISS, LLM readiness 확인 |
| `/metrics` | Prometheus scrape endpoint |
| `/status` | 버전, Python, platform, dependency 상태 |

중요한 설계 판단:

```text
Redis unavailable != service not ready
```

Redis가 없어도 local memory fallback으로 동작할 수 있으므로 `/readyz`는 Redis unavailable을 곧바로 503으로 보지 않는다.

## 17. 기존 LangGraph식 구조와의 차이

LangGraph의 강점은 명시적 그래프 제어다.

```text
State -> Node A -> condition -> Node B -> Node C
```

HarmoNet은 이와 다르다.

```text
Seed -> Field -> Resonance -> Claim -> Execute -> Feedback Seed
```

비교하면 다음과 같다.

| 관점 | LangGraph식 접근 | HarmoNet식 접근 |
|---|---|---|
| 제어 방식 | 명시적 그래프/상태 전이 | 공명 기반 선택적 활성화 |
| 장점 | 경로가 명확하고 디버깅 쉬움 | 호출 수와 참여 에이전트 수를 줄이기 쉬움 |
| 약점 | 그래프가 커지면 호출과 상태 관리 증가 | 명시적 분기 제어는 상대적으로 약함 |
| 적합한 작업 | 복잡한 절차형 workflow | 비용 민감형 multi-agent routing |

따라서 HarmoNet은 LangGraph를 완전히 대체한다기보다, "비용 효율과 sparse activation이 중요한 작업"에 맞는 대안이다.

## 18. 설계상 한계

HarmoNet이 모든 상황에서 좋은 것은 아니다.

1. 정확한 절차 제어가 필요한 workflow에는 명시적 그래프가 더 낫다.
2. 테스트가 없는 open-ended 작업에서는 cheap validation의 신뢰도가 제한된다.
3. resonance threshold, risk threshold, keyword threshold는 도메인별 tuning이 필요하다.
4. TDA 검증은 근사이며, 실제 의미 품질을 보장하는 것은 아니다.
5. field/resonance 개념은 강력하지만 디버깅 설명 비용이 있다.

## 19. 실제 사용 시 권장 모드

작업 종류별 권장 방식:

| 작업 종류 | 권장 실행 방식 |
|---|---|
| 함수 구현, 알고리즘 문제 | executable code profile + AST validation |
| patch 생성 | patch profile + diff validation |
| 보안 리뷰/설계 리뷰 | validator 포함 |
| 반복되는 내부 작업 | exact cache 활성화 가능 |
| 외부 운영 서비스 | 인증, rate limit, real LLM smoke 필요 |

## 20. 코드 읽는 순서

HarmoNet을 이해하려면 다음 순서로 읽는 것이 좋다.

1. `harmonet/field.py`: Seed와 DataUniverseField
2. `harmonet/resonance.py`: ResonanceDetector와 KuraMotoCoupler
3. `harmonet/agent.py`: HarmoAgent, SeedEncoder, SOCController
4. `benchmark/agents_harmonet_v2.py`: v2 sparse scheduler와 cheap validation
5. `harmonet/store.py`: Redis/FAISS fallback layer
6. `harmonet/llm.py`: LLM backend 선택
7. `harmonet/health.py`: 운영 엔드포인트

## 21. 최종 요약

HarmoNet의 핵심은 "대화를 많이 시키는 멀티에이전트"가 아니라 "작업 신호를 공유 필드에 올리고, 그 신호와 맞는 에이전트만 깨우는 멀티에이전트"라는 점이다.

수식으로 압축하면 다음과 같다.

```text
Seed = encode(task)
Field = Field + deposit(Seed)
Candidates = search(Field, agent_domain)
Resonance = semantic_similarity * phase_coherence * distance_decay
Execute only if Resonance >= threshold
Validate cheaply before invoking more agents
```

그래서 HarmoNet은 다음 문제를 겨냥한다.

```text
How can a multi-agent system preserve quality while reducing unnecessary LLM calls?
```

이 질문에 대한 HarmoNet의 답은 다음이다.

```text
Represent work as compact seeds,
route by resonance,
validate cheaply,
and activate agents sparsely.
```
