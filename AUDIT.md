# HarmoNet 독립 감사 보고서 (adversarial, 2026-09-11)

검토자: Claude Fable (독립 인스턴스, 이전 조언자의 맥락 없이 저장소·데이터·문서만 검토)
대상: `Kevin0424Lee/Harmonet` — `fair-measurement` (HEAD `c79622d`) 및 `main` (`6b453c2`)
방법: 모든 수치를 저장소의 CSV/JSON/로그에서 직접 재계산. 이전 조언자의 결론은 전제로 삼지 않음.

---

## 1. 검증 결과표 (A–H)

| # | 주장 | 판정 | 근거 위치 |
|---|---|---|---|
| A | 6b453c2에서 토큰 집계가 어댑터마다 다름. v1/v2 자체 추정, `llm.py::generate()`는 `usage` 폐기 | **VERIFIED** | `6b453c2:benchmark/agents_harmonet.py:147,187,194-197` (단어수×2, 통신 0 선언), `6b453c2:benchmark/agents_harmonet_v2.py:36-37,452-454` (`_count_tokens`, system_prompt 미집계), `6b453c2:harmonet/llm.py:194-199,270-271,339-345` (`response.usage` 미사용). 구 CrewAI도 실측 아님: `6b453c2:benchmark/agents_crewai.py:166-180` — `crew.usage_metrics` 폴백 `_count_tokens(prompt)*3`; 구 CSV 120행 전부 prompt_tokens가 3의 배수, 반복 3회 값 40/40 동일 (재계산 확인). 구 AutoGen `6b453c2:agents_autogen.py:129-130` 단어수 추정, **system_message 미포함** (교수보고서 표는 "포함"이라 함 — 오류) |
| B | `agents_harmonet_v2.py`는 공명 런타임 미사용 | **VERIFIED** (단서 있음) | HEAD `benchmark/agents_harmonet_v2.py:28-30` import는 `benchmark.tasks`, `harmonet.llm`, `harmonet.usage` 뿐. `field/resonance/KuraMotoCoupler` 참조 0건. 단서: `:207-220` `enable_v1_fallback` (기본 off, `HARMONET_V2_V1_FALLBACK=1`) 경로에서 v1을 지연 import함 — 측정 실행에서는 비활성 |
| C | `scan_field()` 통과 조건은 `cosine_sim >= delta` 하나, 위상은 `max(0.2, coherence)`로 강도만 변조 | **VERIFIED** | `harmonet/resonance.py:266-268` (브루트포스), `:186-188,216-218` (FAISS 경로도 `min_similarity=self.delta`), `:352-357` (`detect_from_seed`). 위상 하한 0.2로 거부 불가 |
| D | `_tda_approximation()`이 β₁=표준편차 변화, β₀=불일치 임계값 | **VERIFIED as stated, 그러나 서술이 오도적** | `resonance.py:458-466` 그대로임. **그러나 이 함수는 폴백이다.** `validate_resonance_with_betti` `:389-396`는 먼저 `_tda_with_scipy` (`:398-442`, single-linkage H0 death time)를 시도하고 scipy 예외 시에만 approximation으로 떨어진다. scipy는 `requirements.txt`에 있고 실제 환경에서 정상 로드되므로 **실행되는 경로는 scipy 경로**다. scipy 경로도 문제는 있다: β₁ 없음, "Wasserstein"은 정렬된 death time의 L1 합(`:435`, 대각선 매칭 무시 → 상계), 임계값 0.05 하드코딩(`:438`), 사실상 "필드가 조금이라도 변했나" 검사. 그리고 `agent.py:471,640`에서 **첫 이벤트는 TDA 결과와 무관하게 통과**. 피어리뷰 M3와 교수보고서 §5의 "β₁을 표준편차 변화로" 서술은 실행되지 않는 코드를 근거로 한 것 |
| E | G1 재측정 1,080행 전부 measured, 수치 | **부분 REFUTED** | `evidence/g1_fair/*.csv` 재계산: repair 600행 + norepair 480행 = 1,080행 (single 120행 별도 → 총 1,200행), 전부 `measured` ✔. 수치 ✔: single 95.0%/244, v2 92.5%/274, v1 92.5%/281, autogen 94.2%/852, crewai 95.0%/980. **LangGraph norepair는 91.7%/1277이지 93.3%가 아니다.** 93.3%는 repair-포함 실행(1278토큰)의 값. 교수보고서 표 1의 LangGraph 행은 두 실행을 섞었다. 짝 비교 v2 vs single 0/38/2 ✔ (mbpp_2, mbpp_7), v1 vs single 0/39/1 ✔ (HumanEval/8) — 재계산 일치 |
| F | SWE-bench 0–29, haiku, 공식 하네스, 11/14/11, 전부 oracle, 노이즈 ±2 | **수치 VERIFIED / 노이즈 측정 REFUTED** | `evidence/swe_fair/haiku_0_30/*.json` resolved 11/14/11 ✔, (a) error_instances 7 ✔, (b) 초기 실패 11·복구 5·drop 6·수리 13회 ✔, (c) 9·4·5·9 ✔. Oracle: `benchmark/swebench_g1.py:356` `_patch_files(instance["patch"])`, 세 조건 모두 `_make_prompt` 경유 ✔. **±2/30은 "동일 조건 반복 실행"으로 측정된 것이 아니다** — COMPARISON.md §11-E:322 "반복 실행 없이 단일 실행"이라고 스스로 적었다. 아래 §2-N4 |
| G | SWE-bench에서 v1 씨앗 루프 LLM 호출 0회, `repair_used=True` | **VERIFIED — 그러나 원인이 누락됨** | `gen_harmonet_validate_anthropic_0_30.txt:18`: `SentenceTransformers 로드 실패 (huggingface-hub ... 1.4.1) → 오프라인 결정론적 대체 모드`. G1 JSON에서도 v1 120/120행 `seeds_received=0, tasks_completed=0, repair_used=True`. 원인은 아래 §2-N1 |
| H | "컨텍스트 검색"은 oracle 파일 제공, 검색 기제 없음 | **VERIFIED** | `swebench_g1.py:356-364,378` ("Relevant file paths from oracle retrieval" 문구 자체가 코드에 있음). `harmonet/` 전체 grep — BM25/retrieval 없음, FAISS는 씨앗 벡터 인덱스(`store.py:285-321`)일 뿐 |

---

## 2. 새로 발견한 문제 (심각도 순)

### N1 [치명] 공명 게이트는 9월 실행 전체에서 **난수 임베딩** 위에서 돌았다 — "기제 기여 없음"이 아니라 "기제가 실행되지 않음"

- `harmonet/embed.py:60-68`: sentence-transformers 로드 실패 시 예외를 삼키고 `offline_mode=True`. `:93-101` `_offline_embed`는 텍스트의 MD5로 `np.random.seed`를 잡고 `randn(384)`을 뽑는다. **임의의 두 텍스트 사이 코사인은 N(0, 0.05)** — 2,000쌍으로 측정: mean 0.000, sd 0.050, P(cos≥0.15)=0.2%.
- 실제 벤치마크 태그로 계산: cos(architect 태그, builder 태그) = **0.020**, builder δ=0.15 (`agents_harmonet.py:67`). 결정론적이므로 **게이트는 절대 열리지 않는다.** Validator는 grid 11, 씨앗은 grid 2 → 거리 9 > scan_radius 5 (`agent.py:442,569`) → 임베딩과 무관하게 애초에 볼 수 없음.
- 증거: SWE-bench 로그 18행에 폴백 경고가 그대로 찍혀 있다. G1 JSON의 v1 120행 전부 `seeds_received=0`. 6월 실행(`evidence/g1/G1_V1_VS_V2_COMPARISON_20260603.md`: v1 488토큰, 7.3s)은 여러 호출을 냈던 정황 → **6월엔 임베딩이 됐고 9월엔 환경이 퇴행했다.**
- 결과: 교수보고서 §5 "세 시험 모두에서 HarmoNet 고유의 기제(공명 게이팅, 쿠라모토, TDA, SOC, 필드 동역학…)는 측정 가능한 기여를 보이지 않았습니다"는 **틀렸다.** v2는 그 기제를 갖지 않았고(B), v1은 기제가 죽은 채 돌았다. 세 시험 중 어느 것도 공명 게이팅을 실행하지 않았다. §7의 "시험되지 않았다"가 맞고 §5는 철회해야 한다. (c) harmonet_validate 11/30은 "HarmoNet 구조"가 아니라 **`Repair this benchmark answer… Missing required terms: diff --git, <gold 파일경로>` 프롬프트 + `_DEFAULT_SYSTEM` "You are a HarmoNet collaborative AI agent… decompress seed formulas into production-ready code"** (`llm.py:327-331,350`, system_prompt 미지정 시 강제 적용)라는 과제와 무관한 프롬프트 조합의 성적이다. 그 조합으로 11/30이 나온 건 오히려 놀랍다.
- 이전 조언자는 "v1의 2틱 파이프라인이 LLM 호출 0회"(COMPARISON §7-2)라는 **증상만 보고했고 원인을 조사하지 않았다.** 이 상태로 디스패치 실험(§4)을 돌리면 조건 C도 난수 위에서 돌아 "C ≪ B → HarmoNet 불성립"이 자동 산출된다.

### N2 [치명] MBPP 진입점 추론 버그 — v2의 짝 비교 2패는 전부 하네스 버그

- `benchmark/external_g1.py:141-146` `_infer_entry_point_from_tests`: 정규식 `assert\s+(\w+)\s*\(`가 `assert set(similar_elements(...)) == set(...)`에서 **`set`**을 진입점으로 잡는다. 첫 20개 중 mbpp_2(`similar_elements`), mbpp_7(`find_char_long`)이 해당(전체 427개 중 약 30개). 그래서 태스크 프롬프트(`:184-186`)는 "The solution must define function `set`"이 되고 `expected_keywords=["set"]`(`:297`).
- v2만 이를 **정적으로 강제**한다: `agents_harmonet_v2.py:443,447` "missing function set / function set not defined" → repair 호출 → "Define `set`" 지시로 코드가 망가짐. norepair JSON의 v2 repair 6행 = 정확히 mbpp_2×3, mbpp_7×3, validation reason 전부 `missing function set`. single은 그 지시를 무시하고 `similar_elements`를 정의해 3/3 통과.
- 따라서 COMPARISON §10-B "HarmoNet이 나쁜 과제 2", §10-C "v2의 저비용 검증이 잡아낸 것은 v2 자신의 builder 프롬프트가 만든 실패", 교수보고서 표 2 "0승 38무 2패", "에스컬레이션이 발동한 6행은 모두 단일 호출이 3/3 통과한 문제" — **전부 이 버그의 산물이다.** 버그를 고치면 v2 vs single은 사실상 0/40/0. 결론이 "HarmoNet ≤ single"에서 "HarmoNet = single"로 바뀐다 (우위 없음은 그대로지만 "해롭다/나쁘다" 서술은 철회). repair-포함 조건 §5의 eval-repair 10행 중 mbpp_2×2, mbpp_7도 오염.

### N3 [중대] 43→50 "시맨틱 수리"는 **히든 테스트 결과를 프롬프트에 넣는다** — 피어리뷰 S1/S2 "SWE-bench 증거는 유효" 무효

- `benchmark/swebench_semantic_repair.py:84-91`은 공식 하네스 `report.json`에서 `FAIL_TO_PASS` 실패 테스트명을 뽑고, `:216` `test_output.txt` 꼬리를 읽어, `:94-119`에서 "Failing tests: …", "Official per-instance report", "Tail of official test output"으로 모델에 준다. FAIL_TO_PASS는 SWE-bench의 채점용 히든 테스트다. 이건 test-set leakage이고 리더보드 기준 실격 사유다.
- 피어리뷰 S1 "100개 중 50개 해결… 18→17→43→50 진행은 방법론적으로 유효", S2 "additive ablation을 이미 갖추고 있다", 재측정_프로토콜 §4 "SWE-bench 50/100과 파이프라인 단계별 기여는 그대로 유효", 교수보고서 부록 A "resolve 수는 유효(공식 하네스)" — **모두 정정.** 43 이하도 oracle 파일 + hints_text(N6) 기반이라 표준 수치와 비교 불가. 현재 0–29 실험은 semantic repair를 안 써서 이 누출은 없다.
- 추가 의심: 구 체인 "17 (에러 0, 빈 패치 69)"는 `swebench_g1.py:99-100` 주석에 적힌 Windows 상대경로 버그(apply-check 전부 실패 → drop → 빈 패치)와 정확히 정합한다. 구 체인 수치는 참고값으로도 쓰지 않는 게 안전하다.

### N4 [중대] "노이즈 바닥 ±2/30, 동일 조건 반복 실행으로 실측"은 사실이 아니다

- 교수보고서 2장 표 "노이즈 측정: 동일 조건 반복 실행으로 실행 간 변동폭 측정 ±2/30", 표 3 캡션 "동일 조건 반복으로 실측". 그러나 COMPARISON §11-C:299는 (a)/(b)/(c) 세 조건 사이에서 수리 개입 없이 뒤집힌 인스턴스 2개(astropy-14995, django-11797)를 세어 사후에 추정한 것이고, §11-E:322는 "반복 실행 없이 단일 실행"이라고 명시한다. 이전 조언자의 두 문서가 서로 모순이며 교수보고서 쪽이 허위다. (a)와 (b)의 1차 호출은 동일 프롬프트라 노이즈 프록시로 쓸 수는 있지만, 그러면 "첫 시도 적용 23 vs 19"(apply 여부만으로 4개 차이)도 같이 보고해야 한다. n=1 쌍에서 나온 ±2는 노이즈 추정치가 아니다.

### N5 [중대] `max_tokens=1024` 절단이 (a)의 "apply 실패"를 만들었다 — 수리 루프 기여의 일부는 자초한 절단의 복구

- `evidence/swe_fair/run_swe_gen.ps1:9` `ANTHROPIC_MAX_TOKENS=1024`. (a) metrics CSV에서 completion_tokens가 정확히 1024인 인스턴스 3개: astropy-7746(패치 끝이 " ```"), django-11564(docstring 중간에서 끊김), django-11910. 7746·11564는 (a)의 하네스 apply 오류 7건에 포함. (b)에서 11564는 수리 3회·2,558 completion으로 살아났고 11910은 2,048 쓰고도 drop.
- 즉 "(b)의 +74% 토큰"과 "적용 불가 패치 11/30"의 일부는 패치 과제에 너무 낮은 출력 한도를 준 파이프라인 아티팩트다. 수리로 복구되어 resolve된 2건(11001, 11422)은 hunk 불일치라 진짜 복구가 맞지만, 서술은 "절단 포함"으로 바꿔야 한다. 최소한 max_tokens를 4096으로 올린 (a′)를 돌려야 "수리 루프 기여"를 말할 수 있다.

### N6 [중대] `hints_text` 포함 — 표준 SWE-bench와 비교 불가, 문서 어디에도 미고지

- `swebench_g1.py:368,377`: `Hints:\n{instance["hints_text"]}`. hints_text는 수정 PR 이전 이슈 코멘트이며 종종 해법을 담는다. 리더보드 시스템(SWE-agent, Agentless 등)은 쓰지 않는다. 세 조건이 같이 받아 within-run 비교엔 영향 없지만, 11/30·14/30 절대값은 "oracle 파일 + hints"라는 이중 특혜 아래 나온 수치로 명시해야 한다. 추가로 `max_file_chars=12000` (`:649`) 절단으로 django 대형 파일은 부분 oracle.
- (a) "검증·수리 없음"도 부정확: `_extract_patch→_clean_patch→_normalize_patch→_recount_hunks` (`:123-229`)는 `:519`에서 **모든 조건에** 적용되는 기계적 형식 수리다. (a)는 "apply-check 없음"이지 "수리 없음"이 아니다. 또 수리 상한은 문서의 "최대 3회"가 아니라 코드상 malformed 2 + hunk 1 + other 1 = 최대 4회(`:531-541`).

### N7 [중간] 교수보고서 표 1은 세 실행을 섞었고 캡션이 틀렸다

- single(별도 실행), v2(norepair 실행), v1(repair 실행), CrewAI/AutoGen(norepair), LangGraph(**토큰은 norepair 1,277, 정확도는 repair 실행의 93.3%**; norepair는 91.7%). "1,080행 전부 실측" 캡션 아래 표는 720행(3개 파일)에서 왔다. 6장 표 "시험 1, n=600"도 마찬가지로 행 수이지 독립 표본이 아니다.

### N8 [중간] 정확도 CI가 과소 — 유효 n은 120이 아니라 40

- 120행 = 40과제 × 3반복. 실패는 과제 단위로 완전 군집한다(HumanEval/10, mbpp_20은 전 시스템 3/3 실패). 이항 CI ±4.6pp(n=120)는 군집을 무시한 값이고, 과제 단위 n=40이면 ±7pp 이상. "single 95.0% (±3.9)"도 같은 문제. 논문에는 과제 단위 부트스트랩 CI를 써야 한다.

### N9 [중간] "추가 토큰은 더 긴 시스템 프롬프트에서" — v2에 대해서는 반대

- v2 builder 1회로 끝난 114행의 평균 prompt는 **156.6** (single 161보다 짧다). v2 시스템 프롬프트(`agents_harmonet_v2.py:340` 12단어)는 single(`agents_single.py:33-37` 33단어)보다 짧다. v2의 +12%는 (i) completion 103 vs 83 (출력이 27% 김 — "No prose unless code comments" 허용 효과), (ii) N2 버그로 2회 호출한 6행. COMPARISON §10-D:243, 교수보고서 4.2 마지막 문장은 v1에만 해당한다.

### N10 [중간] 베이스라인 프롬프트가 비대칭 — "vs LangGraph 78.5%"는 가장 못 튜닝된 베이스라인 대비

- `agents_langraph.py:285-288` builder에 "코드만 반환/진입점 정의" 지시 없음, `:309-312` validator는 "Suggest improvements" (산문). 반면 CrewAI(`agents_crewai.py:137-140`)와 AutoGen(`agents_autogen.py:141-145`)의 validator는 "return only final Python code". 그 결과 LangGraph completion 581 vs AutoGen 231, CrewAI 208 — **1,277 vs 852의 차이는 프레임워크가 아니라 프롬프트 차이다.** 헤드라인을 LangGraph 대비로 잡은 건 최약 베이스라인 선택이다. 대칭 프롬프트로 다시 돌리지 않으면 세 베이스라인 간 순위는 의미 없다.
- 3콜 패턴 자체: plan→build→review는 CrewAI/AutoGen 예제와 MetaGPT류에서 실제로 쓰이므로 순수 허수아비는 아니다. 그러나 (i) 단일 호출이 이미 95%로 포화된 과제에서 리뷰어가 값을 할 여지가 없고(천장 효과), (ii) 7B 리뷰어가 7B 빌더를 고칠 수 있다는 기대 자체가 무리이며, (iii) "3회 호출 ≈ 3배 토큰"은 측정이 아니라 산수다. 배율도 "4~5배"가 아니라 single 대비 3.5×(AutoGen)–5.2×(LangGraph).

### N11 [중간] 교수보고서의 중심 가설 "LLM에게 묻는 검증 vs 현실에 묻는 검증"은 같은 데이터가 반박한다

- G1 repair-포함 조건의 `repair_after_eval`은 **실제 테스트를 실행해 실패 메시지를 주는** "현실에 묻는 검증"이다. 결과: 발동 10행 중 통과 전환 1행, 토큰 2~3배 (COMPARISON §5:131-135). 즉 같은 종류의 기계적 검증이 G1에서는 효과 없었다. 보고서 6장 표는 이 행을 빼고 SWE-bench 쪽만 "+2~3/30"으로 넣었다. 또 "LLM 검증"은 7B·포화 과제, "기계적 검증"은 Haiku·SWE-bench로 모델과 과제가 다르다 — 통제된 비교가 아니다.
- 6장 표 "에이전트 게이팅·스케줄링 +12% 없음 시험 2·3": 시험 3에서 (c)는 (b)보다 토큰이 **−11%**(6,831 vs 7,670)다. 부호가 틀렸다.

### N12 [낮음] 계측 패치의 버그

- `llm.py:488-512` `_wrap_estimating(MockLLMClient)`: `generate_async`를 감싸는데 원본 `generate_async`(`:177-181`)가 내부에서 `self.generate`(이미 감싸짐)를 부른다 → **mock 비동기 호출 1회당 2회 기록.** v1 mock 실행에서 `llm_calls: 2` 확인. 실측 실행엔 영향 없으나 스모크 테스트 수치는 틀린다.
- `usage.py:42-56`: Anthropic `cache_creation_input_tokens`/`cache_read_input_tokens` 미집계. `llm.py:348` 시스템 블록에 `cache_control` 항상 부착. 이번엔 시스템 프롬프트가 Haiku 4.5 캐시 최소 길이(4,096) 미만이라 실제 과소집계는 없었지만 잠재 버그.
- `agents_harmonet.py:128` `METER.reset()`이 docstring 앞에 있어 docstring이 죽었고, v2 `enable_v1_fallback` 시 v1의 reset이 v2 누적을 지운다(`token_source`/`llm_calls`만 오염, 기본 off).
- `agents_autogen.py:166` `token_source="measured"` 하드코딩 — 3호출 중 일부만 usage가 와도 measured.

### N13 [낮음] 기타

- 교수보고서 "테스트 167개 통과": 검토 환경(fastapi 없음, 2파일 제외) 152 passed + 1 skipped. UNVERIFIABLE. TDA 테스트(`tests/test_resonance.py:211-233`)는 반환 타입만 검사한다 — 정확성 테스트 아님.
- `_offline_embed`가 `np.random.seed`를 전역으로 재설정(`embed.py:99`) → 폴백 모드에서 Kuramoto 초기 위상, TDA 노이즈가 텍스트 해시에 종속.
- 재측정_프로토콜 §1 표의 CrewAI 행 "API 실측/포함/포함"은 오류(추정이었음 — COMPARISON §2가 이미 정정).

---

## 3. 이전 조언자 문서 정정 사항 (줄 단위)

### `HarmoNet_피어리뷰.md`
- L32 CrewAI "API 실측 / 포함 / 포함" → "단어수×3 폴백 / 미포함 / 미포함".
- L78-90 F2, L92-108 F3 → 재측정_프로토콜 §0에서 철회됨. 단 F3 축소 후에도 N2(진입점 `set`) 때문에 mbpp_2/7에서 "키워드 강제"가 실제 해를 끼쳤음을 추가.
- L122-139 M3 → "`_tda_approximation`은 scipy 실패 시 폴백. 실행 경로는 `_tda_with_scipy` (H0 single-linkage, β₁ 없음, L1 death-time 합, 임계 0.05, 첫 이벤트 무조건 통과)"로 교체.
- L161-163 S1, S2 → **삭제.** 43→50은 히든 테스트 누출(N3), 전 구간 oracle+hints(N6), 17/100은 Windows 버그 의심.
- L210 "즉시 논문화가 가능한 것은 SWE-bench 기반 주제" → 근거 소멸.

### `재측정_프로토콜.md`
- L30 CrewAI 행, L31 AutoGen "시스템 프롬프트 포함" → 오류.
- L17 "HumanEval/MBPP 정확도 수치는 실제 테스트 실행 기반이 맞고 유효" → "단, mbpp_2·mbpp_7은 진입점 추론 버그(external_g1.py:141-146)로 프롬프트가 `set` 정의를 요구 — v2 결과 오염".
- L169 "SWE-bench 50/100과 파이프라인 단계별 기여는 그대로 유효" → 삭제.

### `HarmoNet_진행보고_및_방향결정.docx`
- 1장 요약 "세 번의 독립적인 시험 모두에서 HarmoNet 고유의 기제는 측정 가능한 기여를 보이지 않았습니다" → "세 시험 중 어느 것도 공명 게이팅을 실행하지 않았다(v2는 미탑재, v1은 임베딩 폴백으로 게이트 사망). 기제의 기여는 **미측정**이다."
- 2장 표 "노이즈 측정 — 동일 조건 반복 실행" → 삭제 또는 "세 조건 간 교차 관찰에서 사후 추정(반복 실행 없음)".
- 3장 표 AutoGen "시스템 프롬프트 포함" → 미포함.
- 표 1 LangGraph 93.3% → 91.7% (norepair). 캡션 "1,080행" → 표 구성 실행 3개와 행 수 720 명시. CI를 과제 단위로 재계산.
- 표 2 및 4.2 본문 "0승 38무 2패", "에스컬레이션 6행은 모두 단일 호출이 3/3 통과한 문제", "추가 토큰은 대부분 더 긴 시스템 프롬프트" → N2·N9 반영 (2패는 하네스 버그; 버그 수정 후 재측정 전엔 "동률"로만 서술).
- 표 3 캡션 "실행 간 노이즈 ±2/30 (동일 조건 반복으로 실측)" → 삭제. 각주에 max_tokens=1024 절단(N5), hints_text·oracle(N6) 명시.
- 4.3 "(a) 단일 호출, 검증 없음" → "apply-check 없음(형식 정규화는 공통)".
- 5장 두 번째 문단 "TDA 검증은 β₁을 표준편차 변화로…" → D 항목대로. "SWE-bench 실행에서 v1의 필드 루프는 LLM 호출을 한 번도 발생시키지 않았습니다" 뒤에 **원인(임베딩 폴백)** 추가 — 이걸 빼면 교수는 "기제가 무용하다"로 읽는다.
- 6장 표 "에이전트 게이팅 +12%" → 시험 3에서는 −11%. "기계적 검증·수리 +74% / +2~3/30" → "n.s., 그중 1건 노이즈, (a) 실패 일부는 출력 절단". G1 eval-repair(현실 검증, 1/10 구제) 행 추가.
- 6장 "LLM에게 묻는 검증은 효과가 없고 현실에 묻는 검증은 효과가 있다" → 교차 비교 근거 없음(모델·과제 상이, G1 반례). 중심 가설로 쓰지 말 것.
- 부록 A "SWE-bench 18→43→50 resolve 수는 유효" → "43→50은 히든 테스트 누출, 전 구간 oracle+hints, 인용 불가".
- 부록 B "테스트 167개" → 실제 실행 결과로 교체.

---

## 4. 디스패치 실험 설계 결함

1. **조건 D가 이길 수밖에 없다.** K=32, 함수 15개, docstring 2~3문장이면 D의 컨텍스트는 ≈ 20~25k 토큰 — Haiku 200k 창의 1/8. 이 규모의 needle-in-haystack은 현대 LLM이 ~99% 맞힌다. 설계서 §5 "D ≥ 모든 조건 (모든 K에서) → 디스패치 무의미"는 사실상 사전 결정된 결론이다. 교차점을 보려면 K가 수백~수천이어야 하고 그건 "만능 하나"가 아니라 RAG의 영역이다 — 그리고 그때 C는 RAG와 구별되지 않는다(아래 3).
2. **사전 등록 규칙이 내부 모순.** 규칙 1(C≈B & 디스패치 토큰≈0 → HarmoNet 성립)과 규칙 3(D≥전부 → 디스패치 무의미)이 동시에 참일 수 있다. 어느 규칙이 우선인지, 정확도·비용을 어떻게 결합해 판정할지(예: "D 대비 정확도 −Xpp 이내 & 토큰 ≤ Y%")를 지금 고정하지 않으면 결과가 나온 뒤 유리한 쪽을 고르게 된다.
3. **조건 C는 표준 임베딩 라우터다.** "질문 임베딩 vs 문서 임베딩 코사인 ≥ δ"는 RAG의 검색 단계 그 자체다. 설계서 §9가 인용하는 Google 블랙보드 논문의 비용 기준선이 이미 RAG(2.3배)이므로, C의 결과는 "RAG ≈ RAG"다. `resonance.py`가 그 위에 얹는 것은 (i) 적응형 δ, (ii) 위상 곱(게이트 아님), (iii) TDA(첫 이벤트 통과), (iv) 그리드 거리 필터, (v) 선점 지연 — 문서 QA에서 의미를 갖는 건 (i)뿐이고 나머지는 난수다. HarmoNet이 RAG 라우터와 다른 점을 실험 전에 명문화하지 못하면 이 실험은 HarmoNet을 검증하는 게 아니다.
4. **C3 ≈ C2는 구조적으로 보장된다 → 어블레이션이 무의미.** 조건 C는 "통과한 에이전트만 답한다"인데 위상은 통과 여부에 관여하지 않는다(§1-C). 순위를 쓰지 않는 설계에서 위상 곱은 어떤 결과도 바꿀 수 없다. 규칙 "C3 ≈ C2 → 쿠라모토 제거"는 실험 없이도 참이다. 위상을 시험하려면 top-1 선택 규칙을 넣어야 하고, 그러면 위상이 무작위 초기화(`resonance.py:56,145`)라 노이즈 항일 뿐이다.
5. **적응형 δ가 K와 실행 순서에 종속.** `update_adaptive_delta` (`:297-339`)는 5스캔마다 공명률 <5%면 δ를 −0.02 내린다. K개 중 정답 1개면 공명률 ≈ 1/K → K≥32에서 δ가 계속 내려가 후반 태스크일수록 오탐이 는다. 태스크 순서 무작위화·δ 초기값·δ 궤적 보고가 없으면 재현 불가. δ 초기값 자체가 자유 매개변수라 사후 튜닝 여지가 있다 — 홀드아웃에서 고정해야 한다.
6. **`resonance.py` 실사용 시 그리드 거리 필터가 재현율을 무작위로 깎는다.** `scan_field`는 `abs(grid_pos − scan_position) > scan_radius`면 씨앗을 버린다(`:206-209,250-253`). K=32 에이전트를 16칸 그리드에 두면 절반 이상이 어떤 씨앗도 못 본다. 어댑터가 전원을 같은 칸에 두면 필터는 무효 — 어느 쪽이든 명시 필요.
7. **에이전트 도메인 벡터는 태그 평균이다.** `SeedEncoder.encode_task`/`HarmoAgent`는 문서 15개를 평균 풀링해 하나의 ω로 만든다. 함수별 인덱스(표준 RAG)보다 구조적으로 불리하다. C가 지면 원인이 "벡터 유사도가 거칠어서"(규칙 2)가 아니라 평균 풀링일 수 있는데, 해석표가 이를 구분하지 못한다.
8. **정확도 지표가 디스패치 재현율과 거의 동일하다.** 정답 함수명은 해당 라이브러리 문서에만 있으므로 "응답에 함수명 등장" = "정답 에이전트가 답했는가". 조건 A(브로드캐스트)는 항상 정답 에이전트가 답하므로 정확도 100%가 보장되고, 다중 응답의 최종 답 선택 규칙이 없다. A·B·C 모두에 "최종 응답 하나를 고르는 규칙"이 필요하다.
9. **질문 생성이 C에 유리하게 편향.** 질문은 docstring의 LLM 패러프레이즈이므로 임베딩 상 근사 중복이다. 실제 디스패치가 어려운 건 질문이 불완전·다의적일 때인데 그 경우가 없다. 최소한 "docstring 재서술" 외에 "사용 사례 서술"·"오류 메시지" 유형을 섞어야 한다.
10. **N1을 고치지 않으면 실험 전체가 난수 위에서 돈다.** 설계서 §6 "HarmoNet의 embed.py가 이미 무엇을 쓰는지 확인 후 결정"만으로 부족하다. 러너 시작 시 `assert cos(유사문장) − cos(무관문장) > 0.3` 같은 임베딩 건전성 게이트를 넣고, `offline_mode=True`면 실행을 중단해야 한다.

---

## 5. 종합 판단

**현재 "정직한 실증 노트" 프레이밍은 그대로는 방어할 수 없다.** 세 축을 나눠 보면:

- **"3콜 패턴은 4~5배 비용, 이득 없음"** — 방향은 맞지만 진술이 과하다. (i) 배율은 3.5~5.2×이고 그 차이의 대부분은 프롬프트 튜닝 차이(N10). (ii) 단일 호출이 95%로 포화된 과제에서 리뷰어가 값을 못 하는 건 천장 효과이며, 7B 리뷰어라는 조건이 붙는다. (iii) 3콜 베이스라인은 SWE-bench(여지 있는 과제)에서 돌지 않았다. 방어 가능한 형태: "**7B 모델·포화 과제에서, 저자가 구성한 plan→build→review 3콜 패턴은 단일 호출 대비 3.5~5×의 토큰을 쓰고 정확도 이득이 없었다**(과제 단위 CI 병기)."
- **"single이 HarmoNet과 같다"** — 데이터가 지지하는 가장 단단한 결론이지만, "같거나 나쁘다"는 철회해야 한다(N2). 그리고 이건 HarmoNet **기제**에 대한 결론이 아니다. v2는 기제를 갖지 않고 v1은 기제가 죽어 있었다(N1). 올바른 서술: "**HarmoNet v2(작업 프로파일링·정적 검증·에스컬레이션)는 단일 호출과 구별되지 않는다. 공명 게이팅은 이 데이터에서 실행된 적이 없어 평가되지 않았다.**"
- **"apply-check 수리는 방향상 도움, n.s."** — n.s.는 맞다. 그러나 (a)의 실패에 max_tokens 절단이 섞여 있고(N5), 노이즈 바닥 측정이 없었으며(N4), oracle+hints 조건이라(N6) "방향"조차 조심스럽다. 방어 가능한 형태: "**oracle 파일 컨텍스트 하에서 apply-check 재시도는 hunk 불일치 패치 2/30을 실제로 살렸다(기제 추적 가능). 전체 resolve 차이 +3은 CI 안이며 반복 실행이 없다.**"

**이 데이터가 실제로 지지하는 가장 강한 주장은 하나다:** "동일 모델·동일 엔드포인트·API 실측 토큰·실제 테스트 채점이라는 대칭 조건에서, 오케스트레이션 층(3콜 파이프라인이든 HarmoNet v2든)은 단일 호출 대비 정확도를 올리지 못했고, 비용은 호출 횟수에 비례했다." 이건 학부 워크숍 수준의 **측정 방법론 노트**로는 성립한다. "멀티에이전트 검토 패턴은 비용을 정당화하지 못한다"나 "현실에 묻는 검증이 효과 있다" 같은 일반 명제는 지지되지 않는다.

**교수 미팅 전에 반드시 해야 할 것 (비용 순):**
1. `huggingface-hub` 버전 고정 후 v1을 다시 돌려 `seeds_received>0`를 확인 — 이게 안 되면 HarmoNet에 관한 어떤 문장도 쓸 수 없다. ($0, 로컬)
2. `_infer_entry_point_from_tests` 수정(테스트의 최상위 호출이 아니라 `test_list`에서 builtin이 아닌 첫 식별자, 또는 sanitized-mbpp의 `code`에서 `def` 추출) 후 v2·single만 재실행. ($0)
3. SWE-bench (a)/(b)를 `max_tokens=4096`, hints 제거로 재실행하고, (a)를 2회 반복해 노이즈를 실제로 잰다. (≈ $1.5)
4. 문서 정정(§3). 특히 "노이즈 동일 조건 반복" 문장과 "18→43→50 유효" 문장은 그대로 나가면 교수 신뢰를 잃는 종류의 오류다.

디스패치 실험(경로 2)은 §4의 1·2·3·10을 해결하기 전엔 시작하지 않는 게 맞다. 현재 설계는 결과가 어느 쪽으로 나와도 HarmoNet 고유 기여를 보이지 못하도록 짜여 있다.
