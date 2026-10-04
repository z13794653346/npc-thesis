import json

from fastapi.testclient import TestClient


class DecisionModel:
    model = "test-model"
    configured = True

    def __init__(self):
        self.calls = 0

    async def complete(self, context):
        self.calls += 1
        return {"intent": "intro", "evidence_ids": [], "action_id": None}


def test_api_uses_graph_and_keeps_request_idempotency(tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("NPC_MEMORY_MODE", "lexical")
    model = DecisionModel()
    client = TestClient(create_app(db_path=tmp_path / "modern.sqlite", model=model,
                                  debug_token="test-token"))
    state = client.post("/api/sessions").json()
    payload = {"npc_id": "owner", "text": "你好", "request_id": "modern"}
    url = f"/api/sessions/{state['id']}"
    first = client.post(url + "/interactions", json=payload)
    second = client.post(url + "/interactions", json=payload)
    assert first.json() == second.json()
    assert model.calls == 1
    debug = client.get(url + "/debug", headers={"X-Debug-Token": "test-token"}).json()
    trace = debug["requests"][0]["trace"]
    assert trace["orchestrator"] == "langgraph"
    assert [node["node"] for node in trace["workflow_trace"]] == [
        "restore", "decide", "validate"
    ]
    assert trace["retrieval"]["retrieval_strategy"] == "lexical"
    assert "snapshot" not in trace
    assert "game_state" not in json.dumps(trace)


def test_health_reports_configured_retrieval_without_loading_model(tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("NPC_MEMORY_MODE", "hybrid")
    client = TestClient(create_app(db_path=tmp_path / "health.sqlite", model=DecisionModel()))
    health = client.get("/api/health").json()
    assert health["orchestrator"] == "langgraph"
    assert health["storage_backend"] == "sqlite"
    assert health["memory_mode"] == "hybrid"
    assert health["embedding_model"] == "BAAI/bge-small-zh-v1.5"


def test_rejected_decision_keeps_scoped_evidence_in_debug_trace(tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("NPC_MEMORY_MODE", "lexical")

    class BadDecision(DecisionModel):
        async def complete(self, context):
            return {"intent": "answer", "evidence_ids": ["foreign-fact"], "action_id": None}

    client = TestClient(create_app(db_path=tmp_path / "rejected.sqlite", model=BadDecision(),
                                  debug_token="test-token"))
    state = client.post("/api/sessions").json()
    url = f"/api/sessions/{state['id']}"
    result = client.post(url + "/interactions", json={
        "npc_id": "owner", "text": "秘密", "request_id": "invalid"
    }).json()
    assert result["error"]["code"] == "invalid_evidence"
    assert result["state"] == state
    trace = client.get(url + "/debug", headers={"X-Debug-Token": "test-token"}).json()[
        "requests"
    ][0]["trace"]
    assert trace["retrieval"]["npc_id"] == "owner"
    assert trace["raw_output"]["evidence_ids"] == ["foreign-fact"]
    assert [node["node"] for node in trace["workflow_trace"]] == ["restore", "decide"]


def test_model_timeout_keeps_restore_trace_without_changing_game(tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("NPC_MEMORY_MODE", "lexical")

    class TimedOutModel(DecisionModel):
        async def complete(self, context):
            raise TimeoutError

    client = TestClient(create_app(db_path=tmp_path / "timeout.sqlite", model=TimedOutModel(),
                                  debug_token="test-token"))
    state = client.post("/api/sessions").json()
    url = f"/api/sessions/{state['id']}"
    result = client.post(url + "/interactions", json={
        "npc_id": "owner", "text": "你好", "request_id": "timeout"
    }).json()
    assert result["error"]["code"] == "model_timeout"
    assert result["state"] == state
    trace = client.get(url + "/debug", headers={"X-Debug-Token": "test-token"}).json()[
        "requests"
    ][0]["trace"]
    assert trace["retrieval"]["npc_id"] == "owner"
    assert [node["node"] for node in trace["workflow_trace"]] == ["restore"]
