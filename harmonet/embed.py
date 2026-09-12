"""
HarmoNet Embedding Connector
============================
Sentence-Transformers를 연동하여 실제 텍스트 및 태그를 384차원 시맨틱 벡터로 인코딩합니다.
오프라인 환경 또는 라이브러리 부재 시를 대비한 Fallback 모드를 내장합니다.

성능 최적화:
- embed_batch(): 여러 텍스트를 단일 model.encode() 호출로 처리 (N+1회 → 1회)
- _embed_cache: 반복 텍스트 결과를 메모리에 보관하여 재호출 비용 제거
"""

import os
import numpy as np
import hashlib
from typing import Dict, List, Optional, Union

# 글로벌 임베딩 캐시
_transformer_model = None
_embedding_dim = 384
_shared_encoder: "EmbeddingEncoder | None" = None
# 텍스트 → 임베딩 벡터 인메모리 캐시 (반복 태그/문장 중복 연산 방지)
# 크기 상한을 두어 장기 실행 시 메모리 무한 증가를 방지
_embed_cache: Dict[str, np.ndarray] = {}
_EMBED_CACHE_MAXSIZE = 1024   # 초과 시 가장 오래된 25% 항목 일괄 제거 (FIFO)


def get_shared_encoder() -> Union["EmbeddingEncoder", "OpenAIEmbeddingEncoder"]:
    """
    싱글턴 임베딩 엔코더 반환.

    선택 우선순위:
    1. OPENAI_API_KEY 환경변수 설정 시 → OpenAIEmbeddingEncoder (text-embedding-3-small)
       고품질 시맨틱 벡터 + 네이티브 차원 축소 지원
    2. sentence-transformers 설치 시 → EmbeddingEncoder (all-MiniLM-L6-v2, 로컬)
    3. 둘 다 없을 경우 → EmbeddingEncoder (hash 기반 오프라인 폴백)
    """
    global _shared_encoder
    if _shared_encoder is None:
        if os.getenv("OPENAI_API_KEY"):
            try:
                _shared_encoder = OpenAIEmbeddingEncoder(dim=_embedding_dim)
                return _shared_encoder
            except Exception as e:
                print(f"[Embedding] OpenAI 임베딩 초기화 실패 ({e}). "
                      "sentence-transformers로 전환합니다.")
        _shared_encoder = EmbeddingEncoder()
    return _shared_encoder

def get_embedding_dim() -> int:
    return _embedding_dim


# 폴백 허용 스위치. 미설정 시 임베딩 모델 실패는 예외 → 실행 중단.
# 조용한 난수 폴백이 벤치마크 결과를 통째로 무효화한 전력이 있어(AUDIT.md N1) 기본은 fail-closed.
_ALLOW_OFFLINE_ENV = "HARMONET_ALLOW_OFFLINE_EMBED"


def _fallback_or_raise(reason: str) -> None:
    """오프라인 폴백이 명시적으로 허용됐을 때만 통과, 아니면 예외."""
    if os.getenv(_ALLOW_OFFLINE_ENV) == "1":
        print(f"[Embedding] {reason} → {_ALLOW_OFFLINE_ENV}=1 이므로 오프라인 해시 임베딩으로 대체합니다 (의미 없는 벡터!).")
        return
    raise RuntimeError(
        f"[Embedding] {reason}. 해시 폴백은 의미 벡터가 아니므로 중단합니다. "
        f"정말 폴백을 원하면 {_ALLOW_OFFLINE_ENV}=1 을 설정하세요."
    )


def assert_embedding_sane(min_gap: float = 0.3) -> float:
    """
    임베딩 건전성 게이트. 유사 문장 쌍과 무관 문장 쌍의 코사인 차이가 min_gap 이상인지 확인.
    난수 폴백이면 두 값 모두 ≈0이라 차이가 0.05 안팎으로 나와 즉시 실패한다.
    벤치마크 러너 시작 시 호출. 반환값은 측정된 차이.
    """
    enc = get_shared_encoder()
    if getattr(enc, "offline_mode", False):
        raise RuntimeError("[Embedding] offline_mode=True 상태에서는 벤치마크를 실행할 수 없습니다.")
    a, b, c = enc.embed_batch([
        "sort a list of integers in ascending order",
        "order the numbers from smallest to largest",
        "the cat sat on the mat",
    ])
    gap = float(a @ b) - float(a @ c)
    if gap < min_gap:
        raise RuntimeError(
            f"[Embedding] 건전성 검사 실패: cos(유사)-cos(무관)={gap:.3f} < {min_gap}. "
            "임베딩이 의미를 담고 있지 않습니다."
        )
    print(f"[Embedding] 건전성 OK (gap={gap:.3f})")
    return gap

class EmbeddingEncoder:
    """텍스트 임베딩 엔코더"""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.offline_mode = False
        global _transformer_model
        
        if _transformer_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                print(f"[Embedding] 로드 중: {model_name}...")
                _transformer_model = SentenceTransformer(model_name)
                print(f"[Embedding] {model_name} 로드 완료.")
            except Exception as e:
                _fallback_or_raise(f"SentenceTransformers 로드 실패 ({str(e)})")
                self.offline_mode = True

    @staticmethod
    def _truncate_for_embedding(text: str, max_words: int = 180) -> str:
        """
        임베딩 모델의 토큰 한도(all-MiniLM-L6-v2: 256 wordpiece ≈ 180~200 단어)를
        초과하는 텍스트를 앞부분 + 뒷부분 보존 방식으로 트리밍.

        단순 앞자르기 대신 양끝 절반씩 보존하여 의미 손실을 최소화합니다.
        - 앞부분: 작업 의도 (무엇을 할지)
        - 뒷부분: 구체적 조건 (어떻게 할지)

        Args:
            text:      원본 텍스트
            max_words: 허용 최대 단어 수 (기본 180단어 ≈ 220 토큰, 안전 마진 확보)

        Returns:
            트리밍된 텍스트 (원본이 짧으면 그대로 반환)
        """
        words = text.split()
        if len(words) <= max_words:
            return text
        half = max_words // 2
        return " ".join(words[:half]) + " [...] " + " ".join(words[-half:])

    def _offline_embed(self, text: str) -> np.ndarray:
        """오프라인 결정론적 해시 임베딩 (384차원)"""
        vec = np.zeros(_embedding_dim)
        for i in range(4):
            chunk = f"{text}:{i}"
            chunk_hash = int(hashlib.md5(chunk.encode()).hexdigest(), 16)
            np.random.seed(chunk_hash % (2**31))
            vec += np.random.randn(_embedding_dim)
        return vec / (np.linalg.norm(vec) + 1e-8)

    def embed_text(self, text: str) -> np.ndarray:
        """단일 텍스트 문장을 임베딩 벡터로 변환 (캐시 우선)"""
        global _embed_cache
        if text in _embed_cache:
            return _embed_cache[text]

        vec = self.embed_batch([text])[0]
        _embed_cache[text] = vec
        return vec

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """
        여러 텍스트를 단일 model.encode() 호출로 일괄 처리.

        캐시에 없는 텍스트만 실제 추론에 올리고,
        캐시 히트 항목은 결과 행렬에 그대로 조립합니다.

        Returns:
            shape (len(texts), dim) 정규화 벡터 행렬
        """
        global _transformer_model, _embed_cache

        if not texts:
            return np.zeros((0, _embedding_dim), dtype=np.float32)

        result = np.zeros((len(texts), _embedding_dim), dtype=np.float32)

        # 캐시 미스 텍스트만 수집
        miss_indices: List[int] = []
        miss_texts: List[str] = []
        for i, t in enumerate(texts):
            if t in _embed_cache:
                result[i] = _embed_cache[t]
            else:
                miss_indices.append(i)
                miss_texts.append(t)

        if miss_texts:
            if self.offline_mode or _transformer_model is None:
                # 오프라인 모드: 각 미스 텍스트에 결정론적 해시 임베딩
                for idx, text in zip(miss_indices, miss_texts):
                    vec = self._offline_embed(text)
                    result[idx] = vec
                    _embed_cache[text] = vec
            else:
                try:
                    # 256 토큰 한도 초과 텍스트 사전 트리밍 (호출자에게 투명)
                    # 캐시 키는 원본 텍스트 유지 — 트리밍은 model.encode() 직전에만 적용
                    effective_texts = [self._truncate_for_embedding(t) for t in miss_texts]

                    # 단일 배치 추론 (핵심 최적화: N회 → 1회 model.encode())
                    batch_matrix = _transformer_model.encode(
                        effective_texts,
                        batch_size=64,
                        show_progress_bar=False,
                        convert_to_numpy=True,
                    )
                    # L2 정규화 (axis=1, 행별)
                    norms = np.linalg.norm(batch_matrix, axis=1, keepdims=True)
                    batch_matrix = batch_matrix / (norms + 1e-8)
                    for idx, text, vec in zip(miss_indices, miss_texts, batch_matrix):
                        result[idx] = vec
                        _embed_cache[text] = vec
                except Exception as e:
                    _fallback_or_raise(f"배치 추론 에러 ({str(e)})")
                    self.offline_mode = True
                    for idx, text in zip(miss_indices, miss_texts):
                        vec = self._offline_embed(text)
                        result[idx] = vec
                        _embed_cache[text] = vec

        # 캐시 크기 상한 초과 시 오래된 항목 FIFO 제거
        # (miss/hit 여부와 무관하게 매 배치 호출 후 체크)
        # dict는 Python 3.7+ 에서 삽입 순서 보장 → 앞쪽 = 오래된 항목
        if len(_embed_cache) > _EMBED_CACHE_MAXSIZE:
            evict_count = _EMBED_CACHE_MAXSIZE // 4
            for k in list(_embed_cache.keys())[:evict_count]:
                del _embed_cache[k]

        return result

    def embed_tags(self, tags: List[str]) -> np.ndarray:
        """도메인 태그 리스트를 단일 평균 임베딩 벡터로 인코딩 (배치 처리)"""
        if not tags:
            return np.zeros(_embedding_dim)

        # 단일 배치 호출 → 태그 N개를 1회 model.encode()로 처리
        matrix = self.embed_batch(tags)          # (N, 384)
        avg_vector = np.mean(matrix, axis=0)     # (384,)
        # L2 정규화
        return avg_vector / (np.linalg.norm(avg_vector) + 1e-8)


class OpenAIEmbeddingEncoder:
    """
    OpenAI text-embedding-3-small 기반 고품질 시맨틱 임베딩 엔코더.

    EmbeddingEncoder(sentence-transformers) 대비 장점:
    - 더 높은 의미론적 정밀도 (MTEB 벤치마크 기준 상위)
    - 네이티브 차원 축소 지원 (dimensions 파라미터로 384-dim 직접 생성 → 손실 최소)
    - Kolmogorov 압축에 더 가까운 밀도 높은 표현 공간

    API 키: OPENAI_API_KEY 환경변수 또는 생성자 파라미터.
    캐시: EmbeddingEncoder와 동일한 _embed_cache 공유 (전역 1024-항목 FIFO).
    """

    def __init__(self, api_key: Optional[str] = None, dim: int = 384):
        self.dim = dim
        self.model = "text-embedding-3-small"
        _api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not _api_key:
            raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
        from openai import OpenAI
        self.client = OpenAI(api_key=_api_key)
        # offline_mode 속성 — EmbeddingEncoder와 인터페이스 호환
        self.offline_mode = False
        print(f"[Embedding] OpenAI {self.model} 활성화 (차원={dim}). "
              "LLM 임베딩 API 기반 고품질 시맨틱 벡터를 사용합니다.")

    def embed_text(self, text: str) -> np.ndarray:
        """단일 텍스트 임베딩 (캐시 우선)."""
        global _embed_cache
        if text in _embed_cache:
            return _embed_cache[text]
        vec = self.embed_batch([text])[0]
        _embed_cache[text] = vec
        return vec

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """
        여러 텍스트를 단일 OpenAI API 호출로 일괄 처리.
        캐시 히트 항목은 API 호출 없이 바로 반환.

        Returns:
            shape (len(texts), dim) 정규화 벡터 행렬
        """
        global _embed_cache

        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        miss_indices: List[int] = []
        miss_texts: List[str] = []

        for i, t in enumerate(texts):
            if t in _embed_cache:
                result[i] = _embed_cache[t]
            else:
                miss_indices.append(i)
                miss_texts.append(t)

        if miss_texts:
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=miss_texts,
                    dimensions=self.dim,  # 네이티브 축소: PCA 손실 없이 dim-차원 직접 생성
                )
                for list_idx, (orig_idx, api_item) in enumerate(
                    zip(miss_indices, response.data)
                ):
                    vec = np.array(api_item.embedding, dtype=np.float32)
                    norm = np.linalg.norm(vec)
                    vec = vec / (norm + 1e-8)
                    result[orig_idx] = vec
                    _embed_cache[miss_texts[list_idx]] = vec

                # 캐시 크기 상한 초과 시 FIFO 제거
                if len(_embed_cache) > _EMBED_CACHE_MAXSIZE:
                    evict_count = _EMBED_CACHE_MAXSIZE // 4
                    for k in list(_embed_cache.keys())[:evict_count]:
                        del _embed_cache[k]

            except Exception as e:
                _fallback_or_raise(f"OpenAI API 오류 ({e})")
                # 폴백: 해시 기반 결정론적 임베딩
                fallback = EmbeddingEncoder.__new__(EmbeddingEncoder)
                fallback.offline_mode = True
                fallback.model_name = "offline-fallback"
                for orig_idx, text in zip(miss_indices, miss_texts):
                    vec = fallback._offline_embed(text)
                    if vec.shape[0] != self.dim:
                        padded = np.zeros(self.dim, dtype=np.float32)
                        padded[:min(len(vec), self.dim)] = vec[:self.dim]
                        vec = padded / (np.linalg.norm(padded) + 1e-8)
                    result[orig_idx] = vec
                    _embed_cache[text] = vec

        return result

    def embed_tags(self, tags: List[str]) -> np.ndarray:
        """도메인 태그 리스트를 단일 평균 임베딩 벡터로 인코딩."""
        if not tags:
            return np.zeros(self.dim, dtype=np.float32)
        matrix = self.embed_batch(tags)
        avg = np.mean(matrix, axis=0)
        return avg / (np.linalg.norm(avg) + 1e-8)
