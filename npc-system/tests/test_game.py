import pytest


def test_new_state_shape_and_npc_isolation():
    from app.game import new_state

    s = new_state()
    assert s["version"] == 0
    assert set(s["npcs"]) == {"owner", "mechanic", "traveler"}
    assert all(s["npcs"][npc]["trust"] == 50 for npc in s["npcs"])


def test_new_session_isolates_knowledge():
    from app.game import build_context, new_state, player_view

    s = new_state()
    assert len(player_view(s)["npcs"]) == 3
    context, trace = build_context(s, "owner", "维修记录")
    assert "铜铃-731" not in str(context)
    assert "铜铃-731" not in str(player_view(s))
    assert trace["npc_id"] == "owner"


def test_full_return_path():
    from app.game import apply_action, new_state

    s = new_state()
    for task in ["register", "sandbags"]:
        assert apply_action(s, "owner", {"kind": "assist", "target": task})["ok"]
    assert s["npcs"]["owner"]["trust"] == 60
    assert apply_action(s, "owner", {"kind": "confirm_promise"})["ok"]
    assert apply_action(s, "owner", {"kind": "borrow", "target": "key"})["ok"]
    assert apply_action(s, "mechanic", {"kind": "repair"})["ok"]
    assert apply_action(s, "owner", {"kind": "return_item", "target": "key"})["ok"]
    assert s["items"]["key"]["owner"] == "owner"
    assert s["npcs"]["owner"]["trust"] == 70
    assert s["commitments"][0]["status"] == "fulfilled"


def test_duplicate_task_and_unowned_item_are_rejected():
    from app.game import apply_action, new_state

    s = new_state()
    apply_action(s, "owner", {"kind": "assist", "target": "register"})
    assert not apply_action(s, "owner", {"kind": "assist", "target": "register"})["ok"]
    assert s["npcs"]["owner"]["trust"] == 55
    assert not apply_action(s, "traveler", {"kind": "borrow", "target": "key"})["ok"]


def test_over_budget_context_drops_knowledge_last_and_reports_it():
    from app.game import build_context, new_state

    s = new_state()
    for i in range(60):
        s["knowledge"].append(
            {
                "id": f"note-{i}",
                "npc_id": "owner",
                "text": "维修记录" * 20,
                "source": "owner",
                "speaker": "owner",
                "verified": True,
                "learned_at": "",
                "event_id": None,
            }
        )
    context, trace = build_context(s, "owner", "维修记录", budget=4000)
    assert trace["context_chars"] <= 4000
    notes = {f"note-{i}" for i in range(60)}
    kept = {k["id"] for k in context["knowledge"]}
    dropped = set(trace["dropped_knowledge_ids"])
    # Trimming is a partition of the character's knowledge: nothing invented, nothing double-counted.
    assert kept | dropped == notes
    assert not kept & dropped
    assert dropped and len(dropped) < len(notes)


def test_context_budget_error_is_distinct_from_model_output_error():
    from app.game import ContextBudgetError, build_context, new_state

    s = new_state()
    s["scene"]["intro"] = "铺垫" * 3000
    with pytest.raises(ContextBudgetError) as raised:
        build_context(s, "owner", "你好", budget=2000)
    assert raised.value.code == "context_budget_exceeded"
    assert raised.value.size > raised.value.budget
