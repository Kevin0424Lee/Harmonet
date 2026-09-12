# 선행연구 대조 — 1주차 (2026-09-13)

목적: 우리 중심 질문이 아래 연구들과 **어디서 겹치고 어디서 다른지** 확정한다.
"아무도 안 했다"는 결론을 피하기 위해 논문마다 **리뷰어가 "이미 했다"고 인용할 한 문장**을 먼저 적는다.

우리 질문 (WEEK1.md):
> 모델을 재학습하지 않고, 제한된 검증 예산으로 "현재 작업에 추가 협업이 주는 이득"을 학습하여, 협업 상대와 종료 시점을 선택할 수 있는가?

읽은 범위: 4편은 arXiv HTML 전문(BiRouter는 arXiv 2512.00740 = AAAI 2026 채택본), 추가 4편은 초록+본문 일부. 인용문은 원문 영어 그대로.

---

## 1. 지정 4편

| 논문 | 다루는 문제 | 협업 이득을 어떻게 추정하는가 | 비교 실행(counterfactual)을 몇 번 하는가 | 검증 신호 | 온라인 적응 | 우리와 겹치는 부분 | 우리와 다른 부분 | **리뷰어가 "이미 했다"고 인용할 한 문장** |
|---|---|---|---|---|---|---|---|---|
| **Pandora's AI Model Routing Box** (Fisch et al., arXiv 2608.20316) | 이질 모델 풀에서 질의를 어느 전문가에게 보낼지. 가치 추정 자체에 비용이 있음(싼 추정기 vs 비싼 추정기) | 가우시안 신호 모델 하의 **value-of-information** 폐형식. 비싼 추정기(부분 추론 trace 포함)를 볼지 말지를 전문가·입력별로 결정 | **배포 시 0회**. 전문가는 하나만 실행. 반사실은 오프라인 라벨(정답 여부)로 학습·보정 | 정답 여부 − 비용 (`R = 1{correct} − cost`) 등 오프라인 라벨 | **없음**. train/calibration split 로 추정기와 VOI 파라미터를 오프라인 적합 | "추정에도 비용이 든다"는 문제 설정. 부분 추론 trace를 비싼 신호로 쓰는 점(작업 상태 의존) | 결정이 **실행 전 라우팅 1회**. 실행 후 "계속/종료/다른 전문가 추가"가 없음. 온라인 학습 없음. 단일 실행 | "Routing requires estimating each specialist's expected return, but this value estimation has a cost … closed-form value-of-information expressions … determine, for each specialist and input, whether refining the value estimate is worth its cost." |
| **CCPO / SEPO** (Li et al., arXiv 2603.21563) | 협업 LLM RL 의 credit assignment — 공동 보상에서 개별 기여 분리 | **반사실 제거**: 에이전트를 뺀 결과와 비교해 한계 기여 추정 (`R¬1 = R(x, ∅, y2,solo)`) | **훈련 시 N회 협업 롤아웃당 N회 solo 롤아웃 추가** (검증기 호출 2배). 배포 시 0회 | 수학 정답 exact-match, 보상 [−1,1] | **없음**. GRPO/GSPO/REINFORCE++ 로 **가중치 갱신** | "한 에이전트를 뺐을 때와 비교한 한계 기여"라는 양 자체 | 훈련 시 신호(재학습 필요). Think→Solve **고정 파이프라인**, 협업 여부를 런타임에 결정하지 않음. 같은 모델의 역할 분담 | "CCPO estimates an agent's marginal contribution by comparing the realized joint outcome with a counterfactual outcome where that agent is removed." |
| **C3 / Exact Is Easier** (Chen et al., arXiv 2603.06859) | 텍스트 협업은 은닉 상태가 없으므로 credit assignment 를 근사 없이 정확히 | 각 결정 지점에서 이력을 고정하고 **대안 행동 n≥2 개(기본 4)** 를 동결 정책에서 샘플, leave-one-out 기준으로 per-decision advantage | **훈련 시 결정 지점마다 n=4회**. 배포 시 0회 | 수학 정답, 코드 단위 테스트(MBPP+) | **없음**. PPO 로 가중치 갱신 | "이력을 고정하고 대안을 실행해 결정 단위 이득을 잰다" — 우리의 "같은 작업 상태에서 (i)(ii)(iii) 비교"와 형태가 같음 | 훈련 시·가중치 갱신. Duo/Trio **고정 토폴로지**. 같은 모델. 배포 시 적응 없음 | "fix the complete history at each decision point, sample alternative actions under a frozen behavior policy, and compute unbiased per-decision advantages through a parameter-free leave-one-out baseline." |
| **BiRouter** (Yang et al., AAAI 2026 = arXiv 2512.00740) | 자기조직 MAS 에서 각 에이전트가 **런타임에 다음 홉**을 국소 정보만으로 결정 | ImpScore(장기 중요도) + GapScore(현재 작업 상태와의 연속성) 점수 → softmax 로 다음 에이전트 1명 선택. **Finisher 에이전트**가 후보에 있어 종료도 선택 | **배포 시 0회** (홉마다 1명). 라우터는 주석된 라우팅 경로 데이터셋으로 오프라인 지도학습 | 명시적 중간 검증 없음. 사후에 LLM 이 평판 점수를 갱신 | **부분적**: 평판(신뢰도) 승수는 실행 후 LLM 평가로 갱신. 라우팅 점수 자체는 오프라인 | **런타임·작업 상태 조건부·종료 포함** 선택 — 우리 질문의 "협업 상대와 종료 시점 선택"이 이미 있음 | 이득 추정이 학습된 점수이지 **실측 비교가 아님**. 검증 신호가 기계적 검증이 아니라 LLM 평가. 전 에이전트가 **같은 모델(gpt-4o-mini)** + 프로파일 → 모델 이질성 없음 | "This method enables each agent to autonomously execute 'next-hop' task routing at runtime, relying solely on local information … We introduce a special Finisher agent to enable adaptive task completion." |

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

## 3. 한 문단 답: 위 연구가 다루지 않는, 우리가 물을 수 있는 질문은 정확히 무엇인가

코덱스 후보("실행 중인 작업의 상태에 따라 달라지는 협업 이득을, 비싼 비교 실행을 제한적으로만 수행하면서 얼마나 정확하고 저렴하게 배울 수 있는가")는 **구성 요소 단위로는 전부 선행이 있다.** "이득 추정에 비용이 든다 → VOI 로 추정 여부를 결정"은 Pandora 가 했고, "에이전트를 뺀 반사실로 한계 기여를 잰다"는 CCPO·CoFi-PGMA 가, "결정 지점에서 이력을 고정하고 대안 몇 개를 실행해 결정 단위 이득을 잰다"는 C3 가, "런타임에 작업 상태를 보고 다음 협업자 또는 종료를 고른다"는 BiRouter 가, "예산 하에서 한계 신뢰도 이득으로 검증을 계속/중단한다"는 AVA 가 이미 했다. 따라서 후보를 그대로 쓰면 리뷰어는 위 다섯 문장을 인용한다. 남는 것은 교집합이 아니라 **다섯 연구 중 누구도 같이 놓지 않은 세 조건의 결합**이다: (1) 결정이 **실행 후 작업 상태**(산출물 + 기계 검증 결과)에 조건부이고 선택지가 {종료, 같은 모델 자기수정, **다른 모델** 전문가 추가} 셋인 것 — Pandora·ATOM 은 실행 전, AVA 는 단일 모델, BiRouter 는 같은 모델·LLM 평가; (2) 그 선택을 **가중치 갱신 없이 배포 중 온라인으로** 배우는 것 — CCPO·C3·CoFi 는 훈련 시, Pandora·BiRouter·AVA 는 오프라인 보정; (3) 학습 신호가 **제한된 횟수의 실제 반사실 실행 + 기계적 검증(테스트/apply-check)** 인 것 — C3 는 훈련 시에만, BiRouter 는 LLM 평판. 이 결합은 검색 범위에서 찾지 못했지만, **결합 신규성은 약한 주장**이며 심사에서 "Pandora + AVA + BiRouter 를 붙인 것"으로 읽힐 위험이 크다. 그래서 1주차 판단은 이렇다: 우리가 먼저 물어야 할 것은 방법이 아니라 **존재 여부**다 — "같은 작업 상태에서 (i)(ii)(iii) 중 어느 것이 나은지가 실제로 갈리는 경우가, 예산을 맞춘 조건에서, 노이즈 바닥 위로 존재하는가." DISC 가 교차 모델 검증의 이점을 보고했지만 예산 매칭·상태 조건부·종료 옵션 없이였고, 우리 G1·SWE-bench 데이터에서는 아직 그 갈림이 관측되지 않았다(§10·§11: 수리 루프는 방향 신호, HarmoNet 구조는 기여 없음). **이 갈림이 존재한다는 것을 먼저 보이지 못하면 (1)(2)(3)의 결합은 풀 문제가 없다.** 이것이 Part C 설계(`docs/week2_design_draft.md`)의 실험 질문이다.

---

## 4. 검색 범위와 한계
- arXiv HTML 전문: 2608.20316, 2603.21563, 2603.06859, 2512.00740. AAAI OJS PDF(40227/44188)는 암호화돼 읽지 못했고 arXiv 채택본으로 대체.
- 추가 4편은 초록 + 본문 일부(WebFetch 요약)만 읽었다. AVA 는 arXiv id 를 찾지 못해 TMLR 페이지 기준.
- 검색은 영어 키워드 5개 × 2~3 조합. "학습 없이 온라인으로 협업 선택을 배우는" 밴딧 계열은 일반 MAB 논문만 잡혔고 LLM 에이전트 적용은 찾지 못했다 — 없다는 뜻이 아니라 못 찾았다는 뜻이다.
