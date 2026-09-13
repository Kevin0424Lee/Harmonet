# 선행연구 대조 — 1주차 (2026-09-13, B2 갱신)

목적: 우리 중심 질문이 아래 연구들과 **어디서 겹치고 어디서 다른지** 확정한다.
"아무도 안 했다"는 결론을 피하기 위해 논문마다 **리뷰어가 "이미 했다"고 인용할 한 문장**을 먼저 적는다.

우리 질문 (WEEK1.md):
> 모델을 재학습하지 않고, 제한된 검증 예산으로 "현재 작업에 추가 협업이 주는 이득"을 학습하여, 협업 상대와 종료 시점을 선택할 수 있는가?

읽은 범위: 4편은 arXiv HTML 전문(BiRouter는 arXiv 2512.00740 = AAAI 2026 채택본), 추가 4편은 초록+본문 일부. 인용문은 원문 영어 그대로.

---

## 1. 지정 4편

| 논문 | 다루는 문제 | 협업 이득을 어떻게 추정하는가 | 비교 실행(counterfactual)을 몇 번 하는가 | 검증 신호 | 온라인 적응 | 우리와 겹치는 부분 | 우리와 다른 부분 | **리뷰어가 "이미 했다"고 인용할 한 문장** |
|---|---|---|---|---|---|---|---|---|
| **Pandora's AI Model Routing Box** (Fisch et al., arXiv 2608.20316) | 고정된 전문가 풀 중 **최종 선택**. 각 전문가의 가치를 알아보는 검사(inspection)에 비용이 있음 | Pandora's Box: **순차적 유료 검사 + 중단 정책** — 검사를 더 할지, 지금까지 본 것 중 최선을 고르고 멈출지를 VOI 폐형식으로 결정. 검사 정보에는 **부분 출력(초기 추론 trace)이 포함될 수 있음** | 검사는 순차·유료(부분 실행 포함 가능)이나 **최종 실행은 1명**. 반사실 실행 없음 | 오프라인 라벨(정답 여부 − 비용) | **없음**. 오프라인 적합·보정 | "검사에 비용이 있고, 검사를 계속할지 멈출지를 결정한다" — 우리 검증 예산·종료 시점과 구조가 같음 (B2 정정: 실행 전 1회 라우팅이 아니라 순차 검사+중단) | **공동 산출물을 수정해 가는 협업 과정** vs **고정 전문가 중 최종 선택**: Pandora 는 상자(전문가)를 열어 보고 하나를 고르지, 열어 본 결과를 다음 상자의 입력으로 넘기지 않는다. 산출물 상태가 다음 결정의 입력이 되는 구조가 없음 | "Routing requires estimating each specialist's expected return, but this value estimation has a cost … closed-form value-of-information expressions … determine, for each specialist and input, whether refining the value estimate is worth its cost." |
| **CCPO / SEPO** (Li et al., arXiv 2603.21563) | 협업 LLM RL 의 credit assignment — 공동 보상에서 개별 기여 분리 | **반사실 제거**: 에이전트를 뺀 결과와 비교해 한계 기여 추정 (`R¬1 = R(x, ∅, y2,solo)`) | **훈련 시 N회 협업 롤아웃당 N회 solo 롤아웃 추가** (검증기 호출 2배). 배포 시 0회 | 수학 정답 exact-match, 보상 [−1,1] | **없음**. GRPO/GSPO/REINFORCE++ 로 **가중치 갱신** | "한 에이전트를 뺐을 때와 비교한 한계 기여"라는 양 자체 | 훈련 시 신호(재학습 필요). Think→Solve **고정 파이프라인**, 협업 여부를 런타임에 결정하지 않음. 같은 모델의 역할 분담 | "CCPO estimates an agent's marginal contribution by comparing the realized joint outcome with a counterfactual outcome where that agent is removed." |
| **C3 / Exact Is Easier** (Chen et al., arXiv 2603.06859) | 텍스트 협업은 은닉 상태가 없으므로 credit assignment 를 근사 없이 정확히 | 각 결정 지점에서 이력을 고정하고 **대안 행동 n≥2 개(기본 4)** 를 동결 정책에서 샘플, leave-one-out 기준으로 per-decision advantage | **훈련 시 결정 지점마다 n=4회**. 배포 시 0회 | 수학 정답, 코드 단위 테스트(MBPP+) | **없음**. PPO 로 가중치 갱신 | "이력을 고정하고 대안을 실행해 결정 단위 이득을 잰다" — 우리의 "같은 작업 상태에서 (i)(ii)(iii) 비교"와 형태가 같음 | 훈련 시·가중치 갱신. Duo/Trio **고정 토폴로지**. 같은 모델. 배포 시 적응 없음 | "fix the complete history at each decision point, sample alternative actions under a frozen behavior policy, and compute unbiased per-decision advantages through a parameter-free leave-one-out baseline." |
| **BiRouter** (Yang et al., AAAI 2026 = arXiv 2512.00740) | 자기조직 MAS 에서 각 에이전트가 **런타임에 다음 홉**을 국소 정보만으로 결정 | ImpScore(장기 중요도) + GapScore(현재 작업 상태와의 연속성) 점수 → softmax 로 다음 에이전트 1명 선택. **Finisher 에이전트**가 후보에 있어 종료도 선택 | **배포 시 0회** (홉마다 1명). 라우터는 주석된 라우팅 경로 데이터셋으로 오프라인 지도학습 | 명시적 중간 검증 없음. 사후에 LLM 이 평판 점수를 갱신 | **부분적**: 평판(신뢰도) 승수는 실행 후 LLM 평가로 갱신. 라우팅 점수 자체는 오프라인 | **런타임·작업 상태 조건부·종료 포함** 선택 — 우리 질문의 "협업 상대와 종료 시점 선택"이 이미 있음 | 방법 수준 차이만: 이득이 **오프라인 지도학습된 점수**이지 같은 상태의 실측 비교가 아님; 검증 신호가 LLM 평판이지 기계 검증이 아님. (동일 모델 gpt-4o-mini 는 **실험 설정**이지 방법의 제약이 아니므로 차이로 세지 않는다 — B2 정정) | "This method enables each agent to autonomously execute 'next-hop' task routing at runtime, relying solely on local information … We introduce a special Finisher agent to enable adaptive task completion." |

## 1-B. B2 에서 추가 확인한 4편

각 행: 리뷰어가 인용할 한 문장 / 우리와의 차이 / **그 차이가 기여가 되려면 무엇을 보여야 하는지**.

| 논문 | 다루는 문제 | 협업 이득 추정 | 반사실 실행 | 검증 신호 | 온라인 적응 | 겹침 | 차이 | 인용될 한 문장 | 차이가 기여가 되려면 |
|---|---|---|---|---|---|---|---|---|---|
| **KABB** (Zhang et al., ICML 2025, arXiv 2502.07350) — 본문 확인 | 다중 전문가 중 과제별 **부분집합** 선택 | 지식 거리 + 이력 성과 + 팀 시너지로 Thompson sampling; Beta 사후분포를 과제 완료 후 성과(성공률·사용자 평점)로 갱신 (`α ← γ^Δt α + r + δ·KM`) | 없음 (선택한 부분집합만 실행) | 성공률·사용자 평점 | **있음** — 사후분포 온라인 갱신, 학습 없음 | 학습 없이 온라인으로 협업 상대를 고름; 전문가가 **서로 다른 모델** | 선택이 **과제 설명에만** 조건부(부분 실행 상태 아님); 항상 부분집합 응답을 집계, 종료 결정 없음 | "a knowledge-aware Thompson Sampling strategy … dynamically routes each task to the best subset of experts" | 실행 **후** 산출물·검증 상태를 조건으로 넣었을 때 과제 설명만 쓸 때보다 선택이 좋아짐을 보여야 함 |
| **Symphony-Coord** (Guan et al., arXiv 2602.00966) — 초록 확인 | 분산 실행에서 서브태스크→에이전트 라우팅을 온라인 밴딧으로 | LinUCB, 과제 요구·에이전트 상태 특징, **지연된 실행 후 피드백**으로 갱신; sublinear regret | 없음 | 실행 후 피드백/투표 보상 | **있음** (LinUCB 온라인) | 온라인 밴딧 라우팅, 지연 피드백 처리 | 라우팅 대상이 서브태스크 분배; "계속/종료" 없음; 동일 상태 반사실 없음 | "transforms agent selection into an online multi-armed bandit problem … an adaptive LinUCB selector that routes subtasks using context features … updated through delayed post-execution feedback" | 서브태스크 분배가 아니라 **한 산출물의 개선 여부**에 대한 선택에서 regret 이 줄어듦을 보여야 함 |
| **REDEREF** (Hosseini et al., arXiv 2603.13256) — 본문 확인 — **가장 가까움** | 재귀 위임(recursive delegation)에서 훈련 없이 어느 에이전트를 부를지 | Thompson sampling. 신념 = "지금 이 에이전트를 부르면 **순 한계 기여가 양(+)일 확률**"; 판정기(y∈{0,1})의 성공 여부로 `α+=y, β+=1−y` 갱신. **한계 기여는 반사실이 아니라 호출 후 성공 여부** | 없음 | 프로그램 판정(EM/F1/단위 테스트)이 확실한 성공을 단락, 나머지는 보정된 LLM 판정 | **있음** (훈련 없음, 사후분포) | 훈련 없음 · 런타임 재귀 위임 · **한계 기여** 언어 · 종료(성공/깊이/예산/개선 정체) · 기계 판정 우선 | 사전분포를 **질의 유사도·시간 감쇠**로 초기화하고, 판정 결과에 따라 **재라우팅·종료**한다. 조건화하지 않는 것은 **실행 후 산출물·가시 검증 출력 상태**이며, 이득 추정이 **실측 반사실이 아니라 성공 여부 사후분포**라는 점. 단일 에이전트 재시도 대조군 없음(과제 설계상 단일 불가) | "belief-guided delegation via Thompson sampling to prioritize agents with historically positive marginal contributions … without training or fine-tuning" | **같은 상태 s 에서 호출/비호출을 실제로 실행해 잰 이득이, 성공 여부 사후분포보다 더 좋은 선택을 낳는지** — 이 차이의 가치는 **미확인** |
| **CoCoMaMa** (Rau et al., HyperAgents 2025, CEUR Vol-4084 short10, pp.80–94) — **존재 확인, 본문 확인 불가**(PDF 암호화; CEUR 색인 페이지로 제목·저자만 확인) | 휘발성 에이전트 풀(A2A 에이전트 카드)에서 조합 밴딧 라우팅 | (본문 미확인 — 요약 인용 안 함) | — | — | 색인 요약상 온라인 피드백 학습 | 온라인 밴딧 라우팅 | (본문 미확인) | (인용 불가 — 본문 미확인) | 본문 확인 후 기입 |

## 2. 키워드 검색으로 추가한 근접 연구 (2026)

검색어: counterfactual · marginal contribution · when to collaborate · adaptive agent selection · verification budget.

| 논문 | 다루는 문제 | 이득 추정 | 반사실 실행 | 검증 신호 | 온라인 적응 | 겹침 | 차이 | **인용될 한 문장** |
|---|---|---|---|---|---|---|---|---|
| **Anytime Verified Agents (AVA)** (Patel, TMLR 2026) | 예산 안에서 탐색·샘플링·**검증**에 컴퓨트를 동적 배분 | 보정된 불확실성 + **한계 신뢰도 이득** 추정으로 계속/중단 | 배포 시 없음 | 검증 캐스케이드(조기 종료) — 방식 불명시 | 오프라인 보정 | "현재 작업 상태에 따라 검증에 더 쓸지 멈출지"를 예산 하에 결정 — 우리 (i) 종료 vs 계속과 겹침 | **단일 에이전트**. 다른 모델의 전문가 추가라는 선택지가 없음. 온라인 학습 없음 | "AVA … dynamically allocates compute across search, sampling, and verification within a user-specified budget … based on uncertainty and estimated marginal reliability gains." |
| **ATOM** (Zhao et al., arXiv 2605.26178) | 예산 제어 가능한 협업 그래프 | 질의 난이도 추정으로 전자(electron) 에이전트 활성화 수 조절 | 없음 | 과제 정확도 | 오프라인 RL 백본 + 런타임 활성화 | "질의별로 협업 규모를 조절" | 난이도는 **사전** 추정, 실행 중 상태·검증 결과로 갱신하지 않음 | "a stable, offline-learned collaboration backbone and dynamically activated query-conditioned agents … a complexity-aware budgeting strategy aligns resource consumption with task demands." |
| **DISC** (arXiv 2606.21724) | 자기수정이 맞는 답을 망치는 문제 | 검증 질문 출력을 잡음 측정으로 보고 반복 수정 | 없음 | 검증 질문(LLM) | 없음 | **교차 모델 역할 배정이 자기확인 편향을 줄인다** — 우리 (ii) 자기수정 vs (iii) 다른 모델 전문가의 근거 | 고정 패스 수, 상태 조건부 중단 없음, 예산 매칭 불명 | "cross-model role allocation — assigning verification and judgment to a model different from the generator — mitigates self-confirmation bias." |
| **CoFi-PGMA** (arXiv 2604.22785) | 필터된 피드백 하 다중 에이전트 LLM 학습 | 한계 기여 기반 반사실 per-agent 목적 | 훈련 시 | 과제 보상 | 없음(가중치 갱신) | 한계 기여 | 훈련 시 방법 | "derives a counterfactual per-agent training objective based on marginal contribution." (초록) |
| **Semantic Cooperative Games** (arXiv 2607.18255) | LLM MAS 기여 귀속 | 협조 게임(Shapley 류) | 분석 시 | — | 없음 | 기여 귀속 | 사후 분석, 런타임 결정 아님 | (초록 수준) |

---

## 3. 한 문단 답: 위 연구가 다루지 않는, 우리가 물을 수 있는 질문은 정확히 무엇인가 (B2 재작성)

가장 가까운 선행은 **REDEREF** 다. 훈련 없이, 런타임 재귀 위임에서, "이 에이전트를 부르면 한계 기여가 양일 확률"을 Thompson sampling 으로 배우고, 기계 판정을 우선하는 판정기로 성공 여부를 받아 사후분포를 갱신하며, 성공·깊이·예산·정체로 종료한다 — 코덱스 후보의 언어("협업 이득", "한계 기여", "종료 시점", "학습 없이")는 거의 전부 REDEREF 초록에 있다. KABB(ICML 2025)와 Symphony-Coord 는 같은 종류의 온라인 밴딧 선택을 각각 전문가 부분집합·서브태스크 분배에 적용했고, Pandora 는 순차 유료 검사와 중단을 VOI 로 다뤘으며, BiRouter 는 상태 조건부 next-hop 과 종료를 지도학습으로 했다. 그러므로 "결합 신규성"이라는 서술은 버린다. 남는 것은 **REDEREF 대비 방법 수준 차이 하나**다: REDEREF 의 이득 추정치는 *질의 유사도·이력으로 초기화되고 판정 결과로 갱신되는 성공 여부 사후분포* 인 반면, 우리는 *같은 작업 상태 s 에서 호출/비호출(종료·자기수정·다른 모델 전문가)을 실제로 실행해 기계 검증으로 잰 반사실 이득* 을 신호로 쓰고, 그 신호를 제한된 예산 안에서만 얻는다. 이 차이가 가치가 있는지는 **미확인**이다 — 반사실 실측이 사후분포보다 더 나은 선택을 만들지, 그 비용을 상쇄할 만큼 상태 의존 이득이 실제로 존재하는지, 우리 G1·SWE-bench 데이터(§10·§11)는 아직 보여주지 못했다. 따라서 2주차 실험 질문은 방법 비교가 아니라 그 전제의 존재 검증이다: **같은 상태에서 종료 / 자기수정 / 다른 모델 전문가의 우열이 실제로 갈리는 경우가, 예산을 맞추고 노이즈 바닥 위에서, 존재하는가.** 존재하면 3주차에 REDEREF 식 사후분포와 반사실 실측을 같은 데이터로 비교한다. 존재하지 않으면 REDEREF 대비 차이는 기여가 아니다.

## 4. 검색 범위와 한계
- arXiv HTML 전문: 2608.20316, 2603.21563, 2603.06859, 2512.00740. AAAI OJS PDF(40227/44188)는 암호화돼 읽지 못했고 arXiv 채택본으로 대체.
- 추가 4편은 초록 + 본문 일부(WebFetch 요약)만 읽었다. AVA 는 arXiv id 를 찾지 못해 TMLR 페이지 기준.
- B2: KABB·REDEREF 는 arXiv HTML 본문, Symphony-Coord 는 초록, CoCoMaMa 는 CEUR 색인 페이지(PDF 암호화로 본문 확인 불가 — 요약 인용 안 함).
