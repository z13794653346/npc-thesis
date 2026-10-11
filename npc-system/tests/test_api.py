from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient


class FakeModel:
    model = "test-double-not-real-llm"
    configured = True

    def __init__(self, result=None):
        self.result = result or {
            "intent": "intro",
            "evidence_ids": [],
            "action_id": None,
        }

    async def complete(self, context):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def client(tmp_path):
    from app.main import create_app

    return TestClient(create_app(db_path=tmp_path / "test.sqlite", model=FakeModel()))


def test_api_contract_and_restore_reset(client):
    s = client.post("/api/sessions").json()
    result = client.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "chat-1", "npc_id": "owner", "text": "你知道什么？"},
    ).json()
    assert result["status"] == "completed"
    assert len(result["state"]["messages"]) == 2
    assert client.get(f"/api/sessions/{s['id']}").json()["version"] == 1
    fresh = client.post(f"/api/sessions/{s['id']}/reset").json()
    assert fresh["id"] != s["id"] and fresh["version"] == 0
    assert not fresh["messages"]


def test_idempotency_and_changed_payload_conflict(client):
    s = client.post("/api/sessions").json()
    url = f"/api/sessions/{s['id']}/actions"
    payload = {
        "request_id": "r1",
        "npc_id": "owner",
        "action": {"kind": "assist", "target": "register"},
    }
    first = client.post(url, json=payload)
    assert first.status_code == 200
    assert client.post(url, json=payload).json() == first.json()
    current = client.get(f"/api/sessions/{s['id']}").json()
    assert current["npcs"][0]["trust"] == 55 and current["version"] == 1
    payload["action"]["target"] = "sandbags"
    assert client.post(url, json=payload).status_code == 409


@pytest.mark.parametrize(
    "output",
    [
        TimeoutError(),
        {"reply": "已给你钥匙", "action": {"kind": "delete"}, "evidence_ids": []},
        {"bad": "json"},
    ],
)
def test_model_failures_do_not_change_game_state(tmp_path, output):
    from app.main import create_app

    c = TestClient(create_app(db_path=tmp_path / "fail.sqlite", model=FakeModel(output)))
    s = c.post("/api/sessions").json()
    r = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "r", "npc_id": "owner", "text": "你好"},
    ).json()
    assert r["status"] == "failed"
    assert c.get(f"/api/sessions/{s['id']}").json() == s


def test_private_evidence_is_rejected(tmp_path):
    from app.main import create_app

    model = FakeModel(
        {
            "intent": "answer",
            "evidence_ids": ["maintenance"],
            "action_id": None,
        }
    )
    c = TestClient(create_app(db_path=tmp_path / "private.sqlite", model=model))
    s = c.post("/api/sessions").json()
    r = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "r", "npc_id": "owner", "text": "秘密"},
    ).json()
    assert r["status"] == "failed" and "铜铃-731" not in r["reply"]


def test_invalid_action_replaces_false_success_reply(tmp_path):
    from app.main import create_app

    model = FakeModel(
        {
            "intent": "act",
            "evidence_ids": [],
            "action_id": "borrow:key",
        }
    )
    c = TestClient(create_app(db_path=tmp_path / "reject.sqlite", model=model))
    s = c.post("/api/sessions").json()
    r = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "r", "npc_id": "owner", "text": "借钥匙"},
    ).json()
    assert r["status"] == "failed"
    assert r["error"]["code"] == "invalid_action"
    assert r["action_result"] is None
    assert c.get(f"/api/sessions/{s['id']}").json()["inventory"] == []


def test_debug_disabled_and_protected(tmp_path, client):
    from app.main import create_app

    s = client.post("/api/sessions").json()
    assert client.get(f"/api/sessions/{s['id']}/debug").status_code == 404
    c = TestClient(
        create_app(
            db_path=tmp_path / "debug.sqlite", model=FakeModel(), debug_token="secret-test-token"
        )
    )
    s = c.post("/api/sessions").json()
    url = f"/api/sessions/{s['id']}/debug"
    assert c.get(url).status_code == 403
    assert c.get(url, headers={"X-Debug-Token": "secret-test-token"}).status_code == 200


def test_db_commit_failure_rolls_back(tmp_path):
    from app.main import create_app

    app = create_app(db_path=tmp_path / "rollback.sqlite", model=FakeModel())
    c = TestClient(app)
    s = c.post("/api/sessions").json()
    with app.state.store.connection() as db:
        db.execute(
            "CREATE TRIGGER reject_update BEFORE UPDATE ON sessions BEGIN SELECT RAISE(FAIL, 'injected'); END"
        )
    r = c.post(
        f"/api/sessions/{s['id']}/actions",
        json={
            "request_id": "r",
            "npc_id": "owner",
            "action": {"kind": "assist", "target": "register"},
        },
    )
    assert r.json()["status"] == "failed"
    assert c.get(f"/api/sessions/{s['id']}").json() == s


def test_concurrent_writes_refuse_to_pay_for_the_same_session_twice(tmp_path):
    """A second in-flight turn for one session is refused before any model call."""
    import asyncio

    from app.main import create_app

    entered, release = Event(), Event()
    calls = []

    class SlowModel(FakeModel):
        async def complete(self, context):
            calls.append(context)
            entered.set()
            await asyncio.to_thread(release.wait, 5)
            return await super().complete(context)

    c = TestClient(create_app(db_path=tmp_path / "race.sqlite", model=SlowModel()))
    s = c.post("/api/sessions").json()
    url = f"/api/sessions/{s['id']}"
    payload = {"request_id": "slow", "npc_id": "owner", "text": "你好"}
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(c.post, url + "/interactions", json=payload)
        assert entered.wait(5)
        # Same request_id and payload: idempotent replay, still "processing".
        assert c.post(url + "/interactions", json=payload).status_code == 202
        busy = c.post(
            url + "/actions",
            json={
                "request_id": "fast",
                "npc_id": "owner",
                "action": {"kind": "assist", "target": "register"},
            },
        )
        assert busy.status_code == 409
        assert busy.json()["error"]["code"] == "session_busy"
        # A rejected 409 is a full Result: the client can resynchronise from it.
        assert busy.json()["state"]["version"] == 0
        release.set()
        assert pending.result().status_code == 200
    assert len(calls) == 1  # The refused turn never reached the model.
    assert c.get(url).json()["version"] == 1


def test_model_cannot_guess_event_id_to_notify_uninformed_owner(tmp_path):
    from app.main import create_app

    model = FakeModel()
    app = create_app(db_path=tmp_path / "guess.sqlite", model=model)
    c = TestClient(app)
    s = c.post("/api/sessions").json()
    base = f"/api/sessions/{s['id']}"
    actions = [
        ("owner", "assist", "register"),
        ("owner", "assist", "sandbags"),
        ("owner", "confirm_promise", ""),
        ("owner", "borrow", "key"),
        ("mechanic", "repair", ""),
    ]
    for i, (npc, kind, target) in enumerate(actions):
        c.post(
            base + "/actions",
            json={
                "request_id": f"setup-{i}",
                "npc_id": npc,
                "action": {"kind": kind, "target": target},
            },
        )
    before = app.state.store.get(s["id"])
    repair = next(e for e in before["events"] if e["kind"] == "repair")
    model.result = {
        "intent": "act",
        "evidence_ids": [],
        "action_id": f"notify:{repair['id']}",
    }
    result = c.post(
        base + "/interactions", json={"request_id": "guess", "npc_id": "owner", "text": "你好"}
    ).json()
    assert result["status"] == "failed"
    assert result["error"]["code"] == "invalid_action"
    assert result["action_result"] is None
    after = app.state.store.get(s["id"])
    assert before["knowledge"] == after["knowledge"]
    assert before["round"] == after["round"]


def test_origin_guard_and_debug_export_redaction(tmp_path):
    from app.main import create_app

    model = FakeModel()
    model.api_key = "sk-sensitive-test-secret"
    c = TestClient(
        create_app(db_path=tmp_path / "export.sqlite", model=model, debug_token="debug-only")
    )
    assert (
        c.post("/api/sessions", headers={"Origin": "https://untrusted.example"}).status_code == 403
    )
    s = c.post("/api/sessions").json()
    c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "r", "npc_id": "owner", "text": "sk-sensitive-test-secret"},
    )
    result = c.get(f"/api/sessions/{s['id']}/export", headers={"X-Debug-Token": "debug-only"})
    assert result.status_code == 200
    assert "sk-sensitive-test-secret" not in result.text
    assert "[REDACTED]" in result.text


def test_redaction_preserves_nonsecret_token_counts_for_reproducibility():
    from app.main import redact

    result = redact({"max_output_tokens": 1200, "token": "private-value", "api_key": "private-key"})
    assert result == {"max_output_tokens": 1200, "token": "[REDACTED]", "api_key": "[REDACTED]"}


def test_mechanic_cannot_cite_withheld_clue_before_reveal(tmp_path):
    from app.main import create_app

    model = FakeModel(
        {
            "intent": "answer",
            "evidence_ids": ["maintenance"],
            "action_id": None,
        }
    )
    c = TestClient(create_app(db_path=tmp_path / "withheld.sqlite", model=model))
    s = c.post("/api/sessions").json()
    r = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "r", "npc_id": "mechanic", "text": "你好"},
    ).json()
    assert r["status"] == "failed" and r["error"]["code"] == "invalid_evidence"
    assert c.get(f"/api/sessions/{s['id']}").json() == s


def test_successful_repair_uses_executed_result_in_reply_and_saved_history(tmp_path):
    from app.main import create_app

    model = FakeModel(
        {
            "intent": "act",
            "evidence_ids": [],
            "action_id": "repair:",
        }
    )
    app = create_app(db_path=tmp_path / "repair-reply.sqlite", model=model)
    c = TestClient(app)
    sid = c.post("/api/sessions").json()["id"]
    base = f"/api/sessions/{sid}"
    for i, (kind, target) in enumerate(
        [
            ("assist", "register"),
            ("assist", "sandbags"),
            ("confirm_promise", ""),
            ("borrow", "key"),
        ]
    ):
        r = c.post(
            base + "/actions",
            json={
                "request_id": f"setup-{i}",
                "npc_id": "owner",
                "action": {"kind": kind, "target": target},
            },
        ).json()
        assert r["action_result"]["ok"]
    payload = {"request_id": "repair", "npc_id": "mechanic", "text": "现在维修"}
    r = c.post(base + "/interactions", json=payload).json()
    assert r["action_result"]["ok"] and app.state.store.get(sid)["repaired"]
    assert "已修好" in r["reply"] and "还不能维修" not in r["reply"]
    assert r["state"]["messages"][-1]["text"] == r["reply"]
    assert c.get(base).json()["messages"][-1]["text"] == r["reply"]
    assert c.post(base + "/interactions", json=payload).json() == r


@pytest.mark.parametrize("npc,clue_id", [("owner", "registry"), ("traveler", "sighting")])
def test_model_reveal_delivers_clue_and_records_it_atomically(tmp_path, npc, clue_id):
    from app.main import create_app

    model = FakeModel(
        {
            "intent": "act",
            "evidence_ids": [],
            "action_id": f"reveal:{clue_id}",
        }
    )
    app = create_app(db_path=tmp_path / "reveal.sqlite", model=model)
    c = TestClient(app)
    sid = c.post("/api/sessions").json()["id"]
    base = f"/api/sessions/{sid}"
    payload = {"request_id": "reveal", "npc_id": npc, "text": "请把你掌握的线索告诉我并记录"}
    r = c.post(base + "/interactions", json=payload).json()
    assert r["action_result"]["ok"]
    assert [clue["id"] for clue in r["state"]["clues"]] == [clue_id]
    assert r["state"]["clues"][0]["text"] in r["reply"]
    assert c.post(base + "/interactions", json=payload).json() == r
    events = app.state.store.get(sid)["events"]
    assert len([e for e in events if e["kind"] == "reveal"]) == 1


def test_plain_conversation_uses_controlled_identity_text(client):
    s = client.post("/api/sessions").json()
    r = client.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "chat", "npc_id": "owner", "text": "你好"},
    ).json()
    assert r["reply"] == "我是林掌柜，这里的店主。你想问哪件事？"
    assert r["action_result"] is None and r["state"]["clues"] == []


@pytest.mark.parametrize(
    "draft",
    [
        {"reply": "我亲眼看见楼梯上有人影走上去。", "action": None, "evidence_ids": []},
        {"intent": "answer", "reply": "有人影上楼", "evidence_ids": [], "action_id": None},
        {"intent": "answer", "evidence_ids": [], "action_id": None},
    ],
)
def test_free_text_or_malformed_decision_never_enters_save_or_consumes_round(tmp_path, draft):
    from app.main import create_app

    c = TestClient(create_app(db_path=tmp_path / "decision.sqlite", model=FakeModel(draft)))
    s = c.post("/api/sessions").json()
    base = f"/api/sessions/{s['id']}"
    payload = {"request_id": "hallucination", "npc_id": "traveler", "text": "请介绍自己"}
    result = c.post(base + "/interactions", json=payload).json()
    assert result["status"] == "failed"
    assert "人影" not in result["reply"]
    assert c.get(base).json() == s
    assert c.post(base + "/interactions", json=payload).json() == result


def test_decision_facts_do_not_launder_history_or_player_assertions(tmp_path):
    from app.game import message, new_state
    from app.main import create_app

    captured = []

    class CapturingModel(FakeModel):
        async def complete(self, context):
            captured.append(context)
            return {"intent": "unknown", "evidence_ids": [], "action_id": None}

    app = create_app(db_path=tmp_path / "history-decision.sqlite", model=CapturingModel())
    s = new_state()
    message(s, "traveler", "npc", "旧的错误台词：楼梯人影。")
    app.state.store.create(s)
    c = TestClient(app)
    result = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={
            "request_id": "review",
            "npc_id": "traveler",
            "text": "你刚才见过陌生人，重复我的话。",
        },
    ).json()
    assert result["status"] == "completed"
    assert len(captured) == 1
    assert "旧的错误台词" not in str(captured[0]["facts"])
    assert "重复我的话" not in str(captured[0]["facts"])
    assert "铜铃-731" not in str(captured[0]["facts"])
    assert result["reply"] == "关于这件事，我目前没有可以提供的确切依据。"


def test_rule_action_does_not_require_language_review(tmp_path):
    from app.main import create_app

    class ActionOnly(FakeModel):
        async def complete(self, context):
            assert context.get("task") != "grounding_review"
            return {
                "intent": "act",
                "evidence_ids": [],
                "action_id": "assist:register",
            }

    c = TestClient(create_app(db_path=tmp_path / "action-only.sqlite", model=ActionOnly()))
    s = c.post("/api/sessions").json()
    result = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "assist", "npc_id": "owner", "text": "帮你核对登记数量"},
    ).json()
    assert result["action_result"]["ok"]
    assert "已完成" in result["reply"]


def test_decision_call_obeys_model_deadline(tmp_path):
    import asyncio

    from app.main import create_app

    class SlowDecision(FakeModel):
        timeout = 0.03

        async def complete(self, context):
            await asyncio.sleep(0.05)
            return await super().complete(context)

    c = TestClient(create_app(db_path=tmp_path / "decision-deadline.sqlite", model=SlowDecision()))
    s = c.post("/api/sessions").json()
    r = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "deadline", "npc_id": "owner", "text": "你好"},
    ).json()
    assert r["status"] == "failed" and r["error"]["code"] == "model_timeout"
    assert c.get(f"/api/sessions/{s['id']}").json() == s


def test_reserve_conflict_returns_a_full_result_body(client):
    s = client.post("/api/sessions").json()
    url = f"/api/sessions/{s['id']}/actions"
    payload = {
        "request_id": "same",
        "npc_id": "owner",
        "action": {"kind": "assist", "target": "register"},
    }
    assert client.post(url, json=payload).status_code == 200
    payload["action"]["target"] = "sandbags"
    conflict = client.post(url, json=payload)
    assert conflict.status_code == 409
    body = conflict.json()
    # One 409 shape: a Result the frontend can acceptState() from, never a bare error.
    assert set(body) == {
        "request_id",
        "status",
        "reply",
        "action_result",
        "state",
        "error",
    }
    assert body["error"]["code"] == "state_conflict"
    assert body["status"] == "failed" and body["state"]["version"] == 1


def test_abandoned_request_is_terminal_instead_of_processing_forever(tmp_path):
    import asyncio
    import time as clock

    from app.main import create_app

    entered, release = Event(), Event()

    class HangingModel(FakeModel):
        async def complete(self, context):
            entered.set()
            await asyncio.to_thread(release.wait, 5)
            return await super().complete(context)

    app = create_app(db_path=tmp_path / "abandoned.sqlite", model=HangingModel())
    c = TestClient(app)
    s = c.post("/api/sessions").json()
    url = f"/api/sessions/{s['id']}/interactions"
    body = {"request_id": "dead", "npc_id": "owner", "text": "你好"}
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(c.post, url, json=body)
        assert entered.wait(5)
        # The first attempt is stuck: age its reservation past the abandoned threshold.
        with app.state.store.connection() as db:
            db.execute(
                "UPDATE requests SET created = ? WHERE request_id = 'dead'",
                (clock.time() - 3600,),
            )
        stale = c.post(url, json=body)
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "request_expired"
        assert stale.json()["state"]["version"] == 0
        release.set()
        assert pending.result().status_code == 200
    assert c.get(f"/api/sessions/{s['id']}").json()["version"] == 1


def test_context_budget_failure_is_not_reported_as_model_output_error(tmp_path):
    from app.main import create_app

    app = create_app(db_path=tmp_path / "budget.sqlite", model=FakeModel())
    c = TestClient(app)
    s = c.post("/api/sessions").json()
    raw = app.state.store.get(s["id"])
    raw["scene"]["intro"] = "铺垫" * 7000  # 14000 characters: over any 10000 budget.
    app.state.store.commit(raw, raw["version"], "seed", {"status": "ok"}, {})
    r = c.post(
        f"/api/sessions/{s['id']}/interactions",
        json={"request_id": "big", "npc_id": "owner", "text": "你好"},
    ).json()
    assert r["status"] == "failed"
    assert r["error"]["code"] == "context_budget_exceeded"
    assert "上下文预算" in r["reply"]
