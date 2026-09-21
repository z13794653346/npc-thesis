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
