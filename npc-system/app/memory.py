"""Local Chinese embeddings rank only the already authorized candidate set."""

import hashlib
import math
from collections import OrderedDict
from threading import Lock

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
DEFAULT_CACHE_DIR = "artifacts/embedding-models"


def lexical_relevance(query, text, aliases):
    terms = set(query)
    relevance = len(terms & set(text)) / max(1, len(terms))
    for group in aliases.values():
        if any(a in query for a in group) and any(a in text for a in group):
            relevance = max(relevance, 0.8)
    return relevance


def lexical_rank(candidates, query, current_round, aliases):
    """Keep the original experiment baseline and stable ID tie breaking."""
    ranked = []
    for memory in candidates:
        relevance = lexical_relevance(query, memory["text"], aliases)
        recency = 1 / (1 + max(0, current_round - memory["round"]))
        score = 0.6 * relevance + 0.2 * recency + 0.2 * memory["importance"]
        ranked.append({**memory, "score": round(score, 6)})
    return sorted(ranked, key=lambda memory: (-memory["score"], memory["id"]))


class HybridMemoryRetriever:
    """One application-owned model with bounded, model/text-hashed vector cache.

    The cache stores vectors, never role permissions or selected fact IDs. A lock
    protects model initialization/inference and the LRU across workflow threads.
    Requests cannot download models. Run prepare_embeddings.py then restart the
    application to retry a previously unavailable local model.
    """

    def __init__(self, cache_dir=DEFAULT_CACHE_DIR, max_cache_entries=2048, model_factory=None):
        if max_cache_entries < 1:
            raise ValueError("max_cache_entries must be positive")
        self.cache_dir = str(cache_dir)
        self.max_cache_entries = max_cache_entries
        self._model_factory = model_factory
        self._model = None
        self._load_attempted = False
        self._vectors = OrderedDict()
        self._lock = Lock()

    def _load_model(self):
        if self._load_attempted:
            return self._model
        self._load_attempted = True
        try:
            factory = self._model_factory
            if factory is None:
                from fastembed import TextEmbedding

                factory = TextEmbedding
            self._model = factory(
                model_name=MODEL_NAME,
                cache_dir=self.cache_dir,
                local_files_only=True,
                providers=["CPUExecutionProvider"],
                threads=2,
            )
        except Exception:  # noqa: BLE001 - optional model boundary must preserve lexical service
            # Never expose dependency exceptions (which can include local paths).
            self._model = None
        return self._model

    def _vector(self, text):
        key = (MODEL_NAME, hashlib.sha256(text.encode("utf-8")).hexdigest())
        if key in self._vectors:
            self._vectors.move_to_end(key)
            return self._vectors[key]
        vector = tuple(float(value) for value in next(iter(self._model.embed([text]))))
        norm = math.sqrt(sum(value * value for value in vector))
        if not vector or not math.isfinite(norm) or norm == 0:
            raise ValueError("invalid embedding")
        vector = tuple(value / norm for value in vector)
        self._vectors[key] = vector
        if len(self._vectors) > self.max_cache_entries:
            self._vectors.popitem(last=False)
        return vector

    def rank(self, candidates, query, current_round, aliases):
        baseline = lexical_rank(candidates, query, current_round, aliases)
        if not candidates:
            return baseline, {"retrieval_strategy": "empty", "fallback_reason": None}
        with self._lock:
            if self._load_model() is None:
                return baseline, {
                    "retrieval_strategy": "lexical_fallback",
                    "fallback_reason": "model_unavailable",
                }
            try:
                # FastEmbed's ONNX query_embed delegates to embed unchanged.
                # BGE's model card recommends this Chinese query-only instruction:
                # https://huggingface.co/BAAI/bge-small-zh-v1.5
                query_vector = self._vector(QUERY_PREFIX + query)
                ranked = []
                for memory in candidates:
                    vector = self._vector(memory["text"])
                    if len(vector) != len(query_vector):
                        raise ValueError("embedding dimensions differ")
                    cosine = sum(a * b for a, b in zip(query_vector, vector, strict=True))
                    semantic = max(0.0, min(1.0, cosine))
                    lexical = lexical_relevance(query, memory["text"], aliases)
                    recency = 1 / (1 + max(0, current_round - memory["round"]))
                    score = (
                        0.5 * semantic + 0.1 * lexical + 0.2 * recency + 0.2 * memory["importance"]
                    )
                    ranked.append(
                        {
                            **memory,
                            "score": round(score, 6),
                            "semantic_score": round(semantic, 6),
                            "lexical_score": round(lexical, 6),
                            "recency_score": round(recency, 6),
                            "importance_score": memory["importance"],
                        }
                    )
            except Exception:  # noqa: BLE001 - ONNX/tokenizer exceptions vary by runtime
                return baseline, {
                    "retrieval_strategy": "lexical_fallback",
                    "fallback_reason": "embedding_failed",
                }
        return sorted(ranked, key=lambda memory: (-memory["score"], memory["id"])), {
            "retrieval_strategy": "semantic_hybrid",
            "embedding_model": MODEL_NAME,
            "fallback_reason": None,
        }
