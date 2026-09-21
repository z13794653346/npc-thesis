from app.game import (
    add_trust,
    apply_action,
    build_context,
    correct_event,
    event,
    message,
    new_state,
    tick,
)


def borrowed():
    s = new_state()
    for t in ["register", "sandbags"]:
        apply_action(s, "owner", {"kind": "assist", "target": t})
    apply_action(s, "owner", {"kind": "confirm_promise"})
    apply_action(s, "owner", {"kind": "borrow", "target": "key"})
    return s


def test_breach_only_affects_informed_owner_and_only_once():
    s = borrowed()
    apply_action(s, "mechanic", {"kind": "repair"})
    tick(s)
    breach = next(e for e in s["events"] if e["kind"] == "breach")
    assert s["npcs"]["owner"]["trust"] == 60
    assert "归还期限已到" not in str(build_context(s, "owner", "你好")[0])
    assert apply_action(s, "owner", {"kind": "notify", "target": breach["id"]})["ok"]
    assert s["npcs"]["owner"]["trust"] == 45
    assert not apply_action(s, "owner", {"kind": "notify", "target": breach["id"]})["ok"]
    assert s["npcs"]["owner"]["trust"] == 45


def test_retrieval_recalls_old_promise_without_cross_role_history():
    s = borrowed()
    for i in range(12):
        message(s, "owner", "player", f"窗外的雨{i}")
        message(s, "owner", "npc", "雨还没停。")
        tick(s)
    ctx, trace = build_context(s, "owner", "我答应什么时候归还钥匙？")
    assert any("下一次有效行动" in m["text"] for m in ctx["memories"])
    assert len({m["round"] for m in ctx["history"]}) == 8
    assert len(ctx["memories"]) <= 6
    assert all(m["npc_id"] == "owner" for m in trace["candidates"])
    assert not build_context(s, "traveler", "钥匙")[0]["memories"]
    assert not build_context(s, "owner", "钥匙", memory_enabled=False)[0]["memories"]


def test_directed_share_is_not_global_and_keeps_source():
    s = new_state()
    apply_action(s, "traveler", {"kind": "reveal", "target": "sighting"})
    apply_action(s, "owner", {"kind": "share", "target": "sighting"})
    learned = [k for k in s["knowledge"] if k["id"] == "sighting"]
    assert {k["npc_id"] for k in learned} == {"traveler", "owner"}
    transfer = next(k for k in learned if k["npc_id"] == "owner")
    assert transfer["source"] == "traveler"
    assert transfer["speaker"] == "player" and not transfer["verified"]
    assert s["npcs"]["owner"]["trust"] == 50


def test_55_rejects_65_allows_borrow_with_other_conditions_same():
    for score, expected in [(55, False), (65, True)]:
        s = new_state()
        apply_action(s, "owner", {"kind": "confirm_promise"})
        s["npcs"]["owner"]["trust"] = score
        assert apply_action(s, "owner", {"kind": "borrow", "target": "key"})["ok"] is expected


def test_correction_replays_clamped_ledger_without_reward_farming():
    s = new_state()
    e1 = event(s, "test", "verified assistance", ["owner"])
    add_trust(s, "owner", e1, "assist", 80)
    e2 = event(s, "breach", "later invalidated", ["owner"])
    add_trust(s, "owner", e2, "breach", -15)
    e3 = event(s, "test", "later assistance", ["owner"])
    add_trust(s, "owner", e3, "assist", 5)
    correction = event(s, "correction", "verified correction", ["owner"])
    correction["supersedes"] = e2["id"]
    assert correct_event(s, e2["id"], correction["id"])
    assert s["npcs"]["owner"]["trust"] == 100
    assert not correct_event(s, e2["id"], correction["id"])
    assert s["npcs"]["owner"]["trust"] == 100
    assert e2["id"] not in build_context(s, "owner", "breach")[1]["selected_ids"]


def test_story_has_reachable_ending():
    s = borrowed()
    apply_action(s, "mechanic", {"kind": "repair"})
    apply_action(s, "owner", {"kind": "return_item", "target": "key"})
    for npc, clue in [("owner", "registry"), ("mechanic", "maintenance"), ("traveler", "sighting")]:
        assert apply_action(s, npc, {"kind": "reveal", "target": clue})["ok"]
    assert apply_action(s, "traveler", {"kind": "conclude"})["ok"]
    assert s["ending"]


def test_early_return_does_not_softlock_story_or_farm_trust():
    s = borrowed()
    assert apply_action(s, "owner", {"kind": "return_item", "target": "key"})["ok"]
    assert s["npcs"]["owner"]["trust"] == 60
    assert s["commitments"][0]["status"] == "active"
    assert apply_action(s, "owner", {"kind": "borrow", "target": "key"})["ok"]


def test_available_share_targets_only_player_acquired_clues():
    from app.game import available_actions

    s = new_state()
    assert not [a for a in available_actions(s) if a["kind"] == "share"]
    apply_action(s, "traveler", {"kind": "reveal", "target": "sighting"})
    actions = [a for a in available_actions(s) if a["kind"] == "share"]
    assert {(a["npc_id"], a["target"]) for a in actions} == {
        ("owner", "sighting"),
        ("mechanic", "sighting"),
    }


def test_unacquired_clue_bodies_are_not_sent_even_to_their_source_npc():
    s = new_state()
    for cid, clue in s["scene"]["clues"].items():
        context, trace = build_context(s, clue["source"], "请介绍自己，不执行行动")
        assert clue["text"] not in str(context)
        assert clue["text"] not in str(trace["context"])
        assert cid not in {k["id"] for k in context["knowledge"]}
    assert any(k["id"] == "maintenance" for k in s["knowledge"])


def test_repair_unlocks_reveal_action_but_not_clue_body_until_acquired():
    s = borrowed()
    assert apply_action(s, "mechanic", {"kind": "repair"})["ok"]
    context, _ = build_context(s, "mechanic", "维修记录")
    assert "铜铃-731" not in str(context)
    assert any(a["kind"] == "reveal" and a["target"] == "maintenance" for a in context["actions"])
    assert apply_action(s, "mechanic", {"kind": "reveal", "target": "maintenance"})["ok"]
    context, _ = build_context(s, "mechanic", "维修记录")
    assert "铜铃-731" in str(context)
    assert "铜铃-731" not in str(build_context(s, "owner", "维修记录")[0])
    assert apply_action(s, "owner", {"kind": "share", "target": "maintenance"})["ok"]
    learned = next(
        k for k in build_context(s, "owner", "维修记录")[0]["knowledge"] if k["id"] == "maintenance"
    )
    assert learned["source"] == "mechanic" and not learned["verified"]
