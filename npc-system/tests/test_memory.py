import copy

from app.agents import NpcAgent
from app.game import build_context, event, new_state


class TinyEmbedding:
    """Deterministic vectors test ranking; they do not prove model quality."""

    def __init__(self):
        self.documents = []

    def embed(self, documents):
        for text in documents:
            self.documents.append(text)
            yield [1.0, 0.0] if "修好" in text or "恢复供电" in text else [0.0, 1.0]


def test_semantic_synonyms_outrank_character_overlap_and_report_scores():
    from app.memory import QUERY_PREFIX, HybridMemoryRetriever

    s = new_state()
    correct = event(s, "fixture", "配电箱已经修好", ["owner"])
    event(s, "fixture", "恢复供电四个字写在纸上", ["owner"])
    model = TinyEmbedding()
    # The decoy has character overlap but a different semantic vector.
    original_embed = model.embed

    def embed(documents):
        for text in documents:
            if "纸上" in text:
                model.documents.append(text)
                yield [0.0, 1.0]
            else:
                yield from original_embed([text])

    model.embed = embed
    retriever = HybridMemoryRetriever(model_factory=lambda **kwargs: model)
    payload, trace = build_context(s, "owner", "恢复供电", retriever=retriever)
    assert payload["memories"][0]["id"] == correct["id"]
    assert trace["retrieval_strategy"] == "semantic_hybrid"
    assert trace["fallback_reason"] is None
    assert payload["memories"][0]["semantic_score"] == 1.0
    assert "lexical_score" in payload["memories"][0]
    assert QUERY_PREFIX + "恢复供电" in model.documents


def test_filtering_happens_before_embedding_and_does_not_mutate_state():
    from app.memory import HybridMemoryRetriever

    s = new_state()
    allowed = event(s, "fixture", "配电箱已经修好", ["owner"])
    event(s, "fixture", "外角色秘密", ["mechanic"])
    invalid = event(s, "fixture", "撤销记录", ["owner"])
    invalid["valid"] = False
    before = copy.deepcopy(s)
    model = TinyEmbedding()
    retriever = HybridMemoryRetriever(model_factory=lambda **kwargs: model)
    agent = NpcAgent.restore(s, "owner", "恢复供电", retriever=retriever)
    assert agent.trace["selected_ids"] == [allowed["id"]]
    assert not any("外角色秘密" in text or "撤销记录" in text for text in model.documents)
    assert s == before


def test_missing_model_uses_identical_lexical_ranking_without_path_leak():
    from app.memory import HybridMemoryRetriever

    s = new_state()
    event(s, "fixture", "配电箱已经修好", ["owner"])
    observed = []

    def unavailable(**kwargs):
        observed.append(kwargs)
        raise ValueError("missing model at /private/cache/user")

    retriever = HybridMemoryRetriever(cache_dir="/private/cache/user", model_factory=unavailable)
    baseline, _ = build_context(s, "owner", "修好")
    actual, trace = build_context(s, "owner", "修好", retriever=retriever)
    assert actual["memories"] == baseline["memories"]
    assert trace["retrieval_strategy"] == "lexical_fallback"
    assert trace["fallback_reason"] == "model_unavailable"
    assert "/private/" not in str(trace)
    assert observed[0]["local_files_only"] is True
    assert observed[0]["providers"] == ["CPUExecutionProvider"]


def test_embedding_failure_is_transparent_lexical_fallback():
    from app.memory import HybridMemoryRetriever

    class BrokenEmbedding:
        def embed(self, documents):
            raise RuntimeError("internal ONNX path")

    s = new_state()
    event(s, "fixture", "修好配电箱", ["owner"])
    retriever = HybridMemoryRetriever(model_factory=lambda **kwargs: BrokenEmbedding())
    _, trace = build_context(s, "owner", "修好", retriever=retriever)
    assert trace["retrieval_strategy"] == "lexical_fallback"
    assert trace["fallback_reason"] == "embedding_failed"


def test_cache_reuses_text_vectors_but_edits_generate_new_vectors():
    from app.memory import HybridMemoryRetriever

    s = new_state()
    event(s, "fixture", "配电箱已经修好", ["owner"])
    model = TinyEmbedding()
    retriever = HybridMemoryRetriever(model_factory=lambda **kwargs: model)
    build_context(s, "owner", "恢复供电", retriever=retriever)
    build_context(s, "owner", "恢复供电", retriever=retriever)
    assert model.documents.count("配电箱已经修好") == 1
    s["memories"][0]["text"] = "修改后的事实"
    build_context(s, "owner", "恢复供电", retriever=retriever)
    assert "修改后的事实" in model.documents


def test_disabled_memory_never_loads_model():
    from app.memory import HybridMemoryRetriever

    def unexpected(**kwargs):
        raise AssertionError("disabled memory must not load a model")

    s = new_state()
    event(s, "fixture", "配电箱已经修好", ["owner"])
    retriever = HybridMemoryRetriever(model_factory=unexpected)
    payload, trace = build_context(s, "owner", "恢复供电", False, retriever=retriever)
    assert payload["memories"] == []
    assert trace["retrieval_strategy"] == "disabled"
