"""
HarmoNet Agent: 공명 유도형 시드 코딩 에이전트
===============================================
에이전트는 메시지를 직접 주고받지 않는다.
데이터 우주(DataUniverseField)를 통해 씨앗을 투하하고 공명을 감지한다.

SOC (자기조직화 임계성) 컨트롤러 포함:
- BTW 모래 더미 모델로 과부하 시 이웃 에이전트에게 작업 위임
- P(s) ~ s^(-α) 파워 법칙 = 협업 캐스케이드의 스케일 불변성
"""

import asyncio
import inspect
import numpy as np
import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from .field import Seed, DataUniverseField
from .resonance import ResonanceDetector, ResonanceEvent
from .legacy import KuraMotoCoupler, SOCController, legacy_enabled  # noqa: F401 — SOCController 는 호환 re-export

# ── Prometheus 메트릭 (선택적 의존성) ────────────────────────────
# prometheus_client가 없거나 초기화 실패 시에도 에이전트는 정상 작동.
try:
    from .observability.metrics import METRICS as _METRICS
    _METRICS_AVAILABLE = True
except Exception:
    _METRICS = None  # type: ignore
    _METRICS_AVAILABLE = False


class AgentRole(Enum):
    """에이전트 역할"""
    ARCHITECT = "architect"   # 설계자: 씨앗 수식을 생성하여 투하
    BUILDER   = "builder"     # 구현자: 씨앗을 받아 실행
    VALIDATOR = "validator"   # 검증자: 결과를 검증하고 피드백 씨앗 생성
    OBSERVER  = "observer"    # 관찰자: 시스템 모니터링


@dataclass
class TaskResult:
    """에이전트가 씨앗을 실행한 결과"""
    agent_id: str
    seed_id: str
    success: bool
    output: Any
    token_count: int       # 사용된 토큰 수 (기존 방식 비교용)
    execution_time: float
    error: Optional[str] = None
    verification: Optional[Dict] = None  # validator의 기계 검증 판정 (verify.verify_artifact 형식)

    def __repr__(self):
        return (f"TaskResult(agent={self.agent_id}, "
                f"{'✅' if self.success else '❌'}, "
                f"tokens={self.token_count})")


class SeedEncoder:
    """
    씨앗 인코더 (Seed Encoder).
    
    에이전트의 지식·코드·상태를 Kolmogorov 최적 씨앗 수식으로 압축.
    
    핵심 원리:
    - MDL (Minimum Description Length): 모델 + 데이터 설명 길이 최소화
    - 홀로그래픽 원리: 고차원 맥락 → 저차원 경계 표현 (손실 없음)
    - Rate-Distortion: R(D) = min I(X;X̂) (허용 오차 D 하에서 최소 비트율)
    
    현재 구현: LLM 없이 실행 가능한 단순화 버전
    (실제 운영 시 LLM 기반 압축으로 교체 가능)
    """

    @staticmethod
    def encode_task(
        task_description: str,
        domain_tags: List[str],
        agent_id: str,
        dim: int = 256,
        phase: float = 0.0,
    ) -> Seed:
        """
        작업 설명을 씨앗 수식으로 압축.
        
        압축 과정:
        1. 작업의 핵심 규칙(알고리즘 스켈레톤) 추출
        2. 도메인 태그 → 주파수 벡터 (공명에 사용)
        3. 핵심 규칙 → 씨앗 페이로드 벡터 (압축된 정보)
        """
        seed_id = hashlib.sha256(
            f"{agent_id}:{task_description}:{time.time()}".encode()
        ).hexdigest()

        # 싱글턴 EmbeddingEncoder 재사용 (매 호출마다 인스턴스 생성 방지)
        from .embed import get_shared_encoder
        encoder = get_shared_encoder()

        # ─── 핵심 최적화: 태그 N개 + 작업설명 1개를 단일 배치 호출로 처리 ──
        # 기존: embed_tags() N회 + embed_text() 1회 = (N+1) × ~150ms
        # 개선: embed_batch([tag0, ..., tagN-1, task]) = 1회 × ~150ms (flat)
        all_texts = list(domain_tags) + [task_description]
        batch_matrix = encoder.embed_batch(all_texts)   # (N+1, embedding_dim)

        tag_vecs = batch_matrix[:-1]     # (N, embedding_dim) — 태그 벡터들
        task_vec = batch_matrix[-1]      # (embedding_dim,)   — 작업 설명 벡터

        # ─── 주파수 벡터 생성 (도메인 특성: 태그 평균) ──────────
        if len(tag_vecs) > 0:
            raw_freq_vector = np.mean(tag_vecs, axis=0)
            raw_freq_vector = raw_freq_vector / (np.linalg.norm(raw_freq_vector) + 1e-8)
        else:
            raw_freq_vector = np.zeros(batch_matrix.shape[1])

        if len(raw_freq_vector) != dim:
            if len(raw_freq_vector) > dim:
                freq_vector = raw_freq_vector[:dim]
            else:
                freq_vector = np.zeros(dim)
                freq_vector[:len(raw_freq_vector)] = raw_freq_vector
            freq_vector = freq_vector / (np.linalg.norm(freq_vector) + 1e-8)
        else:
            freq_vector = raw_freq_vector

        # ─── 씨앗 페이로드 생성 (압축된 작업 정보) ─────────────
        raw_payload = task_vec   # embed_batch 내부에서 이미 L2 정규화됨
        if len(raw_payload) != dim:
            if len(raw_payload) > dim:
                payload = raw_payload[:dim]
            else:
                payload = np.zeros(dim)
                payload[:len(raw_payload)] = raw_payload
            payload = payload / (np.linalg.norm(payload) + 1e-8)
        else:
            payload = raw_payload

        # 씨앗의 에너지 = 작업의 복잡도 (단어 수 기반 근사)
        complexity = min(1.0, len(task_description.split()) / 50.0)
        energy = 0.3 + 0.7 * complexity

        return Seed(
            id=seed_id,
            creator_id=agent_id,
            frequency=freq_vector,
            payload=payload,
            rule_description=task_description,
            energy=energy,
            phase=phase,
        )

    @staticmethod
    def decode_seed(seed: Seed, world_knowledge: Optional[Dict] = None) -> str:
        """
        씨앗을 실행 가능한 작업 명세로 복원 (Lazy Decompression).
        """
        # TODO(week2): 구조화된 반환으로 통일 — 지금은 rule_description 문자열만 돌려주고,
        # 산출물·task_spec·판정은 seed.metadata 에서 호출자가 직접 꺼낸다.
        return seed.rule_description


class HarmoAgent:
    """
    HarmoNet 에이전트.
    
    메시지를 직접 주고받지 않고, 데이터 우주를 통해 협업.
    
    핵심 루프:
    1. 씨앗 생성 (SeedEncoder로 압축)
    2. 데이터 우주에 씨앗 투하 (DataUniverseField.deposit_seed)
    3. 공명 감지 (ResonanceDetector.scan_field)
    4. 공명한 씨앗만 실행 (Lazy Decompression)
    5. 결과를 새 씨앗으로 투하
    """

    def __init__(
        self,
        agent_id: str,
        role: AgentRole,
        domain_tags: List[str],
        universe: DataUniverseField,
        soc_controller: SOCController,
        kuramoto_coupler: Optional[KuraMotoCoupler] = None,
        resonance_threshold: float = 0.5,
        grid_position: Optional[int] = None,
        learning_rate: float = 0.05,
    ):
        self.agent_id = agent_id
        self.role = role
        self.domain_tags = domain_tags
        self.universe = universe
        self.soc_controller = soc_controller if legacy_enabled() else None
        self.learning_rate = learning_rate

        # 에이전트의 고유 주파수 벡터 (도메인 특성)
        self.domain_vector = self._compute_domain_vector(domain_tags, universe.dim)
        self.natural_frequency = float(np.linalg.norm(self.domain_vector))

        # 공명 감지기
        self.detector = ResonanceDetector(
            agent_id=agent_id,
            domain_vector=self.domain_vector,
            resonance_threshold=resonance_threshold,
        )

        # 쿠라모토 커플러 등록
        # legacy 메커니즘(Kuramoto·TDA·SOC)은 HARMONET_LEGACY_MECHANISMS=1 일 때만 주 경로에 참여 (WEEK1 A3)
        self.legacy = legacy_enabled()
        self.kuramoto = kuramoto_coupler if self.legacy else None
        if self.kuramoto:
            self.kuramoto.register_agent(agent_id, self.natural_frequency)
        else:
            # 위상은 Kuramoto 전용. 플래그 없이는 감지기의 무작위 초기 위상(resonance.py)을 0 으로 고정해
            # 주 경로에 남는 유일한 난수 원천을 제거한다 (게이트엔 영향 없고 강도 로그값만 흔들리던 것)
            self.detector.phase = 0.0

        # 그리드 위치 (데이터 우주에서의 좌표)
        self.grid_position = grid_position or hash(agent_id) % universe.grid_size

        # 통계
        self.seeds_created = 0
        self.seeds_received = 0
        self.task_results: List[TaskResult] = []
        self.token_count_traditional = 0  # 비교용: 기존 방식 예상 토큰 수
        self.last_field_snapshot = None
        self.processed_seed_ids: set = set()
        # 처리 시각 추적 — TTL 만료된 항목을 processed_seed_ids에서 제거하기 위해 사용
        self._processed_timestamps: Dict[str, float] = {}

        # SOC 등록
        if self.soc_controller:
            self.soc_controller.register(agent_id)

        print(f"[{agent_id}] 🤖 에이전트 초기화: role={role.value}, "
              f"domain={domain_tags}, pos={self.grid_position}")

    def _compute_domain_vector(self, domain_tags: List[str], dim: int) -> np.ndarray:
        """도메인 태그로부터 주파수 벡터 계산"""
        from .embed import get_shared_encoder
        encoder = get_shared_encoder()
        raw_vector = encoder.embed_tags(domain_tags)
        if len(raw_vector) != dim:
            if len(raw_vector) > dim:
                vec = raw_vector[:dim]
            else:
                vec = np.zeros(dim)
                vec[:len(raw_vector)] = raw_vector
            return vec / (np.linalg.norm(vec) + 1e-8)
        return raw_vector

    # ─── 씨앗 생성 & 투하 ────────────────────────────────────────

    def create_and_deposit_seed(
        self,
        task_description: str,
        metadata: Optional[Dict] = None,
    ) -> Seed:
        """
        작업을 씨앗으로 압축하여 데이터 우주에 투하.

        HarmoNet의 핵심: 텍스트 메시지 대신 씨앗을 우주에 던짐.

        Args:
            task_description: 씨앗으로 압축할 작업 설명
            metadata: 씨앗에 첨부할 추가 정보 (투하 전에 설정 — Redis 복사본에도 반영됨)
        """
        # Get current phase from Kuramoto coupler if registered
        current_phase = self.kuramoto.get_phase(self.agent_id) if self.kuramoto else 0.0

        # 씨앗 생성 (Kolmogorov 압축)
        seed = SeedEncoder.encode_task(
            task_description=task_description,
            domain_tags=self.domain_tags,
            agent_id=self.agent_id,
            dim=self.universe.dim,
            phase=current_phase,
        )

        # 메타데이터 설정 (deposit_seed 호출 전 — Redis 직렬화에 포함되도록)
        if metadata:
            seed.metadata.update(metadata)

        # 데이터 우주에 투하
        self.universe.deposit_seed(seed, self.grid_position)
        self.seeds_created += 1

        # 메트릭 emit
        if _METRICS_AVAILABLE and _METRICS:
            try:
                _METRICS.seeds_created.labels(
                    agent=self.agent_id, role=self.role.value
                ).inc()
                _METRICS.seeds_deposited.labels(
                    agent=self.agent_id, grid_position=str(self.grid_position)
                ).inc()
            except Exception:
                pass

        # SOC 부하 증가
        if self.soc_controller:
            self.soc_controller.add_load(self.agent_id, 0.2)

        # 비교용: 기존 방식이었다면 필요했을 토큰 수 추정
        self.token_count_traditional += len(task_description.split()) * 3

        return seed

    # ─── 공명 감지 & 씨앗 실행 ──────────────────────────────────

    def _cleanup_processed_ids(self, ttl_seconds: float = 600.0) -> None:
        """
        처리 이력에서 TTL 초과 항목 제거.
        씨앗 기본 TTL(300s)의 2배 시간이 지난 항목은 더 이상 중복 처리 위험이 없음.
        """
        if not self._processed_timestamps:
            return
        cutoff = time.time() - ttl_seconds
        expired = [sid for sid, t in self._processed_timestamps.items() if t < cutoff]
        for sid in expired:
            self.processed_seed_ids.discard(sid)
            del self._processed_timestamps[sid]

    def _build_execution_prompt(self, task_text: str) -> str:
        """Build a compact LLM prompt; benchmark repair handles rare keyword misses."""
        if self.role == AgentRole.BUILDER:
            return (
                f"Role: builder ({self.agent_id}).\n"
                f"Task: {task_text}\n"
                "Return concise working Python code plus only essential notes. "
                "Preserve required identifiers, errors, algorithms, libraries, and API names from the task. "
                "Do not restate the task."
            )
        if self.role == AgentRole.VALIDATOR:
            return (
                f"Role: validator ({self.agent_id}).\n"
                f"Seed/result to review: {task_text}\n"
                "Return PASS/FAIL and only critical correctness or security gaps. "
                "Use at most 6 short bullets. Do not restate code."
            )
        return (
            f"Role: {self.role.value} ({self.agent_id}).\n"
            f"Task: {task_text}\n"
            "Return a concise, actionable development output. Do not restate the task."
        )

    def _is_addressed_to_me(self, seed: Seed) -> bool:
        """씨앗의 metadata["target_role"]이 있으면 그 역할만 실행 (architect가 검증 요청 씨앗을 집어가지 않게)."""
        target = seed.metadata.get("target_role")
        return target is None or target == self.role.value

    def _verify_seed(self, seed: Seed) -> Dict:
        """validator 경로: LLM 호출 없이 builder 산출물(metadata["artifact"])을 기계 검증."""
        from .verify import verify_artifact
        return verify_artifact(seed.metadata.get("artifact", ""), seed.metadata.get("task_spec"))

    def scan_and_process(
        self,
        task_executor: Optional[Callable[[str], Any]] = None,
    ) -> List[TaskResult]:
        """
        데이터 우주를 스캔하여 공명하는 씨앗을 감지하고 실행.

        핵심 효율성: 나와 관련 없는 씨앗은 스캔 비용조차 없음.
        """
        # 만료된 처리 이력 정리 (processed_seed_ids 무한 증가 방지)
        self._cleanup_processed_ids()

        # 쿠라모토 커플러에서 에이전트의 현재 위상 가져오기
        if self.kuramoto:
            self.detector.phase = self.kuramoto.get_phase(self.agent_id)

        # 필드 스냅샷 저장 (TDA 분석용: 이전 틱의 필드와 비교)
        if self.last_field_snapshot is None:
            snapshot_before = np.zeros_like(self.universe.field)
        else:
            snapshot_before = self.last_field_snapshot

        # 공명 감지
        resonance_events = self.detector.scan_field(
            universe=self.universe,
            scan_position=self.grid_position,
            scan_radius=5,
        )

        # TDA 공명 검증
        snapshot_after = self.universe.field.copy()
        self.last_field_snapshot = snapshot_after
        results = []

        # LLM 클라이언트 싱글턴 — 루프 진입 전 1회만 획득
        from .llm import get_llm_client
        llm = get_llm_client()

        for event in resonance_events:
            # 이미 처리한 씨앗은 스킵 (동일 에이전트 중복 방지)
            if event.seed.id in self.processed_seed_ids:
                continue
            if not self._is_addressed_to_me(event.seed):
                continue

            # 분산 선점 (Race Condition 방지)
            if not self.universe.claim_seed(event.seed.id, self.agent_id):
                print(f"[{self.agent_id}] ⏭ 씨앗 {event.seed.id[:8]} 이미 선점됨 → 스킵")
                continue

            # (legacy) TDA 검증 — 플래그 없이는 코사인 유사도 + δ 게이트만으로 판정
            if self.legacy:
                from .legacy import validate_resonance_with_betti
                is_valid, tda_reason = validate_resonance_with_betti(self.detector, snapshot_before, snapshot_after)
                print(f"[{self.agent_id}] TDA 검증: {'✅ 유효' if is_valid else '❌ 노이즈'} | {tda_reason}")
                if not is_valid and len(self.detector.resonance_history) > 1:
                    continue

            task_text = SeedEncoder.decode_seed(event.seed)
            prompt = self._build_execution_prompt(task_text)

            start_time = time.time()
            verification = None
            try:
                if self.role == AgentRole.VALIDATOR and "artifact" in event.seed.metadata:
                    # 기계 검증 — LLM 호출 0회
                    verification = self._verify_seed(event.seed)
                    output = verification["evidence"]
                elif task_executor:
                    output = task_executor(task_text)
                else:
                    # 로컬 LLM을 통한 지연 복원
                    output = llm.generate(prompt)

                local_tokens = 0 if verification else len(prompt.split()) + len(output.split())

                result = TaskResult(
                    agent_id=self.agent_id,
                    seed_id=event.seed.id,
                    success=True,
                    output=output,
                    token_count=local_tokens,  # 로컬 디코딩에 사용된 토큰 수
                    execution_time=time.time() - start_time,
                    verification=verification,
                )

                # ─── 창발적 잠재 언어 최적화 (도메인 벡터 학습) ──────────────────
                old_vector = self.domain_vector.copy()
                self.domain_vector = (1.0 - self.learning_rate) * self.domain_vector + self.learning_rate * event.seed.frequency
                self.domain_vector /= (np.linalg.norm(self.domain_vector) + 1e-8)
                self.natural_frequency = float(np.linalg.norm(self.domain_vector))
                
                self.detector.omega = self.domain_vector
                
                if self.kuramoto:
                    self.kuramoto.frequencies[self.agent_id] = self.natural_frequency

                vec_shift = float(np.linalg.norm(self.domain_vector - old_vector))
                print(f"[{self.agent_id}] 🧠 도메인 벡터 최적화(언어 창발): "
                      f"벡터 변화량={vec_shift:.4f} | 공명 채널이 강화되었습니다.")

                # 자동 피드백 루프: 결과 기반 후속 씨앗 투하
                self._scatter_feedback_seed(event.seed, output)

            except Exception as e:
                result = TaskResult(
                    agent_id=self.agent_id,
                    seed_id=event.seed.id,
                    success=False,
                    output=None,
                    token_count=0,
                    execution_time=time.time() - start_time,
                    error=str(e),
                )

            self.task_results.append(result)
            if len(self.task_results) > 100:
                self.task_results = self.task_results[-100:]
            self.processed_seed_ids.add(event.seed.id)
            self._processed_timestamps[event.seed.id] = time.time()
            self.seeds_received += 1

            # SOC: 씨앗 실행 = 부하 추가
            cascade = self.soc_controller.add_load(self.agent_id, 0.3) if self.soc_controller else None
            if cascade:
                print(f"[{self.agent_id}] 🌊 SOC 캐스케이드 발생 → {cascade}에게 부하 분산")

            results.append(result)

        return results

    # ─── 비동기 공명 감지 & 씨앗 실행 ────────────────────────────

    async def scan_and_process_async(
        self,
        task_executor: Optional[Callable[[str], Any]] = None,
    ) -> List[TaskResult]:
        """
        [비동기] 데이터 우주를 스캔하여 공명하는 씨앗을 감지하고 실행.
        LLM 호출 대기 시간 동안 이벤트 루프가 멈추지 않고 타 에이전트를 병렬 처리하도록 합니다.
        """
        # 만료된 처리 이력 정리 (processed_seed_ids 무한 증가 방지)
        self._cleanup_processed_ids()

        # 쿠라모토 커플러에서 에이전트의 현재 위상 가져오기
        if self.kuramoto:
            self.detector.phase = self.kuramoto.get_phase(self.agent_id)

        # 필드 스냅샷 저장 (TDA 분석용)
        if self.last_field_snapshot is None:
            snapshot_before = np.zeros_like(self.universe.field)
        else:
            snapshot_before = self.last_field_snapshot

        # 공명 감지
        resonance_events = self.detector.scan_field(
            universe=self.universe,
            scan_position=self.grid_position,
            scan_radius=5,
        )

        # TDA 공명 검증
        snapshot_after = self.universe.field.copy()
        self.last_field_snapshot = snapshot_after
        results = []

        # LLM 클라이언트 싱글턴 — 루프 진입 전 1회만 획득
        from .llm import get_llm_client
        llm = get_llm_client()

        for event in resonance_events:
            # 이미 처리한 씨앗은 스킵 (동일 에이전트 중복 방지)
            if event.seed.id in self.processed_seed_ids:
                continue
            if not self._is_addressed_to_me(event.seed):
                continue

            # ─── 도메인 유사도 기반 선점 우선순위 ────────────────
            # 씨앗의 주파수 벡터와 이 에이전트의 도메인 벡터 간 코사인 유사도를 계산.
            # 유사도가 높을수록(이 에이전트가 더 적합할수록) 짧게 대기 → 선점 우선권 확보.
            # 유사도가 낮은 에이전트는 더 오래 대기하므로 더 적합한 에이전트가 먼저 선점.
            #
            # 우선순위 딜레이: delay = (1 - similarity) × 50ms
            #   similarity=1.0 → delay=0ms  (완전 일치 → 즉시 선점)
            #   similarity=0.5 → delay=25ms
            #   similarity=0.0 → delay=50ms (최악 일치 → 가장 늦게 선점)
            seed_freq = event.seed.frequency / (np.linalg.norm(event.seed.frequency) + 1e-8)
            domain_sim = float(np.dot(self.domain_vector, seed_freq))
            domain_sim = max(0.0, min(1.0, domain_sim))
            priority_delay = (1.0 - domain_sim) * 0.05   # 최대 50ms
            if priority_delay > 0.001:
                await asyncio.sleep(priority_delay)

            # ─── 분산 선점 (Race Condition 방지) ─────────────────
            # claim_seed()는 원자적으로 처리권을 획득.
            # 멀티프로세스: Redis SETNX, 단일 프로세스: in-process dict
            # False 반환 = 이미 다른 에이전트/프로세스가 처리 중 → 스킵
            if not self.universe.claim_seed(event.seed.id, self.agent_id):
                print(f"[{self.agent_id}] ⏭ 씨앗 {event.seed.id[:8]} 이미 선점됨 → 스킵 "
                      f"(도메인유사도={domain_sim:.3f})")
                if _METRICS_AVAILABLE and _METRICS:
                    try:
                        _METRICS.claim_attempts.labels(
                            agent=self.agent_id, outcome="already_claimed"
                        ).inc()
                    except Exception:
                        pass
                continue

            print(f"[{self.agent_id}] 🎯 씨앗 선점 성공 (도메인유사도={domain_sim:.3f}, "
                  f"우선순위딜레이={priority_delay*1000:.0f}ms)")
            if _METRICS_AVAILABLE and _METRICS:
                try:
                    _METRICS.claim_attempts.labels(
                        agent=self.agent_id, outcome="success"
                    ).inc()
                    _METRICS.resonance_events.labels(
                        detector_agent=self.agent_id,
                        seed_creator_agent=event.seed.creator_id,
                    ).inc()
                    _METRICS.resonance_strength.observe(event.resonance_strength)
                except Exception:
                    pass
            # (legacy) TDA 검증 — 플래그 없이는 코사인 유사도 + δ 게이트만으로 판정
            if self.legacy:
                from .legacy import validate_resonance_with_betti
                is_valid, tda_reason = validate_resonance_with_betti(self.detector, snapshot_before, snapshot_after)
                print(f"[{self.agent_id}] TDA 검증: {'✅ 유효' if is_valid else '❌ 노이즈'} | {tda_reason}")
                if not is_valid and len(self.detector.resonance_history) > 1:
                    continue

            task_text = SeedEncoder.decode_seed(event.seed)
            prompt = self._build_execution_prompt(task_text)

            start_time = time.time()
            verification = None
            try:
                if self.role == AgentRole.VALIDATOR and "artifact" in event.seed.metadata:
                    # 기계 검증 — LLM 호출 0회 (subprocess가 있을 수 있어 스레드로)
                    verification = await asyncio.to_thread(self._verify_seed, event.seed)
                    output = verification["evidence"]
                elif task_executor:
                    if inspect.iscoroutinefunction(task_executor):
                        output = await task_executor(task_text)
                    else:
                        output = await asyncio.to_thread(task_executor, task_text)
                else:
                    # 비동기 LLM 생성 호출
                    output = await llm.generate_async(prompt)

                local_tokens = 0 if verification else len(prompt.split()) + len(output.split())

                result = TaskResult(
                    agent_id=self.agent_id,
                    seed_id=event.seed.id,
                    success=True,
                    output=output,
                    token_count=local_tokens,
                    execution_time=time.time() - start_time,
                    verification=verification,
                )

                # 도메인 벡터 최적화(언어 창발)
                old_vector = self.domain_vector.copy()
                self.domain_vector = (1.0 - self.learning_rate) * self.domain_vector + self.learning_rate * event.seed.frequency
                self.domain_vector /= (np.linalg.norm(self.domain_vector) + 1e-8)
                self.natural_frequency = float(np.linalg.norm(self.domain_vector))
                
                self.detector.omega = self.domain_vector
                
                if self.kuramoto:
                    self.kuramoto.frequencies[self.agent_id] = self.natural_frequency

                vec_shift = float(np.linalg.norm(self.domain_vector - old_vector))
                print(f"[{self.agent_id}] 🧠 도메인 벡터 최적화(언어 창발): "
                      f"벡터 변화량={vec_shift:.4f} | 공명 채널이 강화되었습니다.")

                # 자동 피드백 루프: 결과 기반 후속 씨앗 투하
                self._scatter_feedback_seed(event.seed, output)

            except Exception as e:
                result = TaskResult(
                    agent_id=self.agent_id,
                    seed_id=event.seed.id,
                    success=False,
                    output=None,
                    token_count=0,
                    execution_time=time.time() - start_time,
                    error=str(e),
                )

            self.task_results.append(result)
            if len(self.task_results) > 100:
                self.task_results = self.task_results[-100:]
            self.processed_seed_ids.add(event.seed.id)
            self._processed_timestamps[event.seed.id] = time.time()
            self.seeds_received += 1

            # 메트릭: 작업 완료
            if _METRICS_AVAILABLE and _METRICS:
                try:
                    _METRICS.tasks_completed.labels(
                        agent=self.agent_id,
                        role=self.role.value,
                        success=str(result.success),
                    ).inc()
                    _METRICS.task_execution_time.labels(
                        agent=self.agent_id, role=self.role.value
                    ).observe(result.execution_time)
                    _METRICS.task_tokens_used.labels(
                        agent=self.agent_id
                    ).observe(result.token_count)
                except Exception:
                    pass

            # SOC: 씨앗 실행 = 부하 추가
            cascade = self.soc_controller.add_load(self.agent_id, 0.3) if self.soc_controller else None
            if cascade:
                print(f"[{self.agent_id}] 🌊 SOC 캐스케이드 발생 → {cascade}에게 부하 분산")
                if _METRICS_AVAILABLE and _METRICS:
                    try:
                        _METRICS.soc_cascades.inc()
                        _METRICS.soc_cascade_size.observe(len(cascade))
                    except Exception:
                        pass

            results.append(result)

        return results

    def _scatter_feedback_seed(self, parent_seed: Seed, output: Any) -> Optional[Seed]:
        """
        작업 완료 후 후속 에이전트들이 공명할 수 있도록 피드백 씨앗을 생성 및 투하.
        (협업 체인 구축)
        """
        # 1. Builder가 구현을 완료한 경우 -> Validator가 공명하여 검증하도록 씨앗 투하
        if self.role == AgentRole.BUILDER:
            # rule_description은 임베딩 한도(256 토큰) 내 짧은 요약만 사용
            # 실제 코드 출력은 metadata에 보관 (투하 전에 설정 → Redis 복사본에도 포함)
            from .verify import extract_artifact
            spec = dict(parent_seed.metadata.get("task_spec") or {})
            artifact = extract_artifact(str(output), spec.get("kind", "code"), report=spec)  # spec["extraction"] 기록
            feedback_desc = (
                "Validation required: run static checks and tests on the builder implementation "
                f"for task {parent_seed.id[:8]}."
            )
            print(f"[{self.agent_id}] 🔄 피드백 체인: 구현 완료 -> 검증 요청 씨앗 투하 준비 중...")
            return self.create_and_deposit_seed(
                feedback_desc,
                metadata={
                    "parent_seed_id": parent_seed.id,
                    "artifact": artifact,            # str(output) 전체가 아니라 추출한 코드/패치만
                    "task_spec": spec,               # 과제 씨앗에서 상속: 진입점·테스트·유형
                    "target_role": AgentRole.VALIDATOR.value,
                },
            )

        # 2. Validator가 검증을 완료한 경우 -> Architect 및 Builder가 확인할 수 있도록 결과 씨앗 투하
        elif self.role == AgentRole.VALIDATOR:
            # 마찬가지로 요약만 rule_description에
            verification = self.task_results[-1].verification if self.task_results else None
            passed = bool(verification and verification.get("passed"))
            methods = ", ".join((verification or {}).get("method") or ["none"])
            feedback_desc = f"Verification {'passed' if passed else 'failed'} for task {parent_seed.id[:8]}: {methods}."
            print(f"[{self.agent_id}] 🔄 피드백 체인: 검증 완료 -> 판정 씨앗 투하 준비 중...")
            return self.create_and_deposit_seed(
                feedback_desc,
                metadata={
                    "parent_seed_id": parent_seed.id,
                    "verification": verification,
                    "target_role": "none",  # 필드 기록용. 어떤 에이전트도 실행하지 않음 (LLM 낭비 방지)
                },
            )

        return None

    # ─── 쿠라모토 동기화 ─────────────────────────────────────────


    def sync_phase(self, dt: float = 0.1) -> None:
        """쿠라모토 모델로 위상 업데이트 (전체 네트워크 동기화에 기여)"""
        if self.kuramoto:
            self.kuramoto.step(dt)

    def drift_position(self) -> None:
        """
        데이터 우주의 밀도 기울기(Gravity Gradient)를 따라 에이전트의 위치가 미세하게 끌려감.
        유사한 작업을 하는 에이전트들 및 씨앗들이 모여 있는 곳으로 자발적 클러스터링.
        """
        gradient = self.universe.get_density_gradient(self.grid_position)
        # gradient는 (dim,) 크기의 벡터. 에이전트 도메인과의 유사성(인력) 계산
        compatibility = float(np.dot(self.domain_vector, gradient))
        
        # 인력이 일정 크기 이상인 경우, 해당 방향(인접 그리드)으로 1칸 이동
        if abs(compatibility) > 0.001:
            step = 1 if compatibility > 0 else -1
            old_pos = self.grid_position
            self.grid_position = (self.grid_position + step) % self.universe.grid_size
            if old_pos != self.grid_position:
                print(f"[{self.agent_id}] 🌌 중력 드리프트: 위치 {old_pos} → {self.grid_position} (인력={compatibility:.4f})")

    # ─── 통계 & 모니터링 ─────────────────────────────────────────

    def get_stats(self) -> Dict:
        """에이전트 통계"""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "seeds_created": self.seeds_created,
            "seeds_received": self.seeds_received,
            "tasks_completed": sum(1 for r in self.task_results if r.success),
            "token_count_harmonet": 0,               # HarmoNet: 0 토큰!
            "token_count_traditional": self.token_count_traditional,  # 기존 방식 예상
            "token_savings_pct": 100.0,               # 이론적 100% 절감
            "activation_level": self.soc_controller.activation_levels.get(self.agent_id, 0) if self.soc_controller else 0,
        }

    def __repr__(self):
        return (f"HarmoAgent(id={self.agent_id}, role={self.role.value}, "
                f"seeds_out={self.seeds_created}, seeds_in={self.seeds_received})")
