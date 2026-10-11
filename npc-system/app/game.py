"""Deterministic game rules. No database, network or model calls in this module."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SCENE = json.loads(Path(__file__).with_name("scene.json").read_text(encoding="utf-8"))


class ContextBudgetError(ValueError):
    """The assembled context cannot fit the character budget after trimming.

    Distinct from a malformed model answer: the API must not report it as
    ``invalid_output``.
    """

    code = "context_budget_exceeded"

    def __init__(self, message, size=0, budget=0):
        super().__init__(message)
        self.size = size
        self.budget = budget


def now():
    return datetime.now(UTC).isoformat()


def new_state():
    s = {
        "id": str(uuid4()),
        "version": 0,
        "dialogue_version": 2,
        "round": 0,
        "created_at": now(),
        "scene": copy.deepcopy(SCENE),
        "messages": [],
        "events": [],
        "knowledge": [],
        "memories": [],
        "commitments": [],
        "trust_log": [],
        "player_clues": [],
        "items": {"key": {"id": "key", "name": "东翼备用钥匙", "owner": "owner"}},
        "npcs": {k: {**v, "id": k, "trust": 50} for k, v in SCENE["npcs"].items()},
        "tasks": {k: {**v, "id": k, "done": False} for k, v in SCENE["tasks"].items()},
        "repaired": False,
        "ending": None,
    }
    for cid, clue in s["scene"]["clues"].items():
        s["knowledge"].append(
            {
                "id": cid,
                "npc_id": clue["source"],
                "text": clue["text"],
                "source": clue["source"],
                "speaker": clue["source"],
                "verified": True,
                "learned_at": now(),
                "event_id": None,
            }
        )
    return s


def message(s, npc, speaker, text):
    s["messages"].append(
        {"id": str(uuid4()), "npc_id": npc, "speaker": speaker, "text": text, "round": s["round"]}
    )


def event(s, kind, text, witnesses, importance=1.0):
    e = {
        "id": f"event-{len(s['events']) + 1:06d}",
        "kind": kind,
        "text": text,
        "round": s["round"],
        "occurred_at": now(),
        "valid": True,
    }
    s["events"].append(e)
    for npc in witnesses:
        learn_event(s, npc, e, "system", importance)
    return e


def learn_event(s, npc, e, speaker, importance=1.0):
    if any(k["id"] == e["id"] and k["npc_id"] == npc for k in s["knowledge"]):
        return False
    s["knowledge"].append(
        {
            "id": e["id"],
            "event_id": e["id"],
            "npc_id": npc,
            "text": e["text"],
            "source": "system",
            "speaker": speaker,
            "verified": True,
            "learned_at": now(),
        }
    )
    s["memories"].append(
        {
            "id": e["id"],
            "npc_id": npc,
            "text": e["text"],
            "source": "system",
            "round": s["round"],
            "importance": importance,
            "event_id": e["id"],
        }
    )
    return True


def add_trust(s, npc, e, rule, delta):
    if any(
        x["npc_id"] == npc and x["event_id"] == e["id"] and x["rule"] == rule
        for x in s["trust_log"]
    ):
        return
    before = s["npcs"][npc]["trust"]
    after = max(0, min(100, before + delta))
    s["trust_log"].append(
        {
            "npc_id": npc,
            "event_id": e["id"],
            "rule": rule,
            "delta": delta,
            "before": before,
            "after": after,
            "active": True,
            "reason": e["text"],
        }
    )
    s["npcs"][npc]["trust"] = after


def correct_event(s, event_id, correction_id):
    """Only a confirmed superseding event can retract a contribution; never player text."""
    original = next((e for e in s["events"] if e["id"] == event_id), None)
    correction = next((e for e in s["events"] if e["id"] == correction_id), None)
    if not original or not correction or correction.get("supersedes") != event_id:
        return False
    if not correction["valid"] or not original["valid"]:
        return False
    original["valid"] = False
    original["corrected_by"] = correction_id
    for npc in s["npcs"]:
        value = 50
        for entry in s["trust_log"]:
            if entry["npc_id"] != npc:
                continue
            if entry["event_id"] == event_id:
                entry["active"] = False
                entry["corrected_by"] = correction_id
            if entry["active"]:
                value = max(0, min(100, value + entry["delta"]))
        s["npcs"][npc]["trust"] = value
    return True


def tick(s):
    """End of one successful interaction; rejected actions never advance the deadline."""
    s["round"] += 1
    for c in s["commitments"]:
        if (
            c["status"] == "active"
            and c["due_round"] is not None
            and s["round"] >= c["due_round"]
            and s["items"]["key"]["owner"] == "player"
        ):
            c["status"] = "breached"
            e = event(s, "breach", "维修后约定的归还期限已到，玩家仍持有备用钥匙。", [])
            c["breach_event_id"] = e["id"]


def apply_action(s, npc, action):
    """Validate before changing state. Caller commits the complete snapshot atomically."""

    def fail(text):
        return {"ok": False, "message": text}

    if npc not in s["npcs"]:
        return fail("角色不存在。")
    kind, target = action.get("kind"), action.get("target")
    result = ""
    if kind == "assist":
        task = s["tasks"].get(target)
        if not task or task["npc_id"] != npc or task["done"]:
            return fail("任务不存在、角色不匹配或已经完成。")
        task["done"] = True
        result = f"已完成：{task['title']}。"
        e = event(s, "assist", result, [npc], 0.7)
        add_trust(s, npc, e, "assistance", 5)
    elif kind == "confirm_promise":
        if npc != "owner" or s["commitments"] or s["repaired"]:
            return fail("当前不能重复确认这一承诺。")
        text = "借用备用钥匙；维修完成后的下一次有效行动结束前归还。"
        s["commitments"].append(
            {
                "id": "promise-key",
                "npc_id": npc,
                "text": text,
                "status": "active",
                "due_round": None,
            }
        )
        event(s, "promise", text, [npc])
        result = "承诺已明确确认：" + text
    elif kind == "borrow":
        item = s["items"].get(target)
        if not item or item["owner"] != npc:
            return fail("该角色不持有这件物品。")
        if s["npcs"][npc]["trust"] < 60:
            return fail("信任不足60；可先完成两项店主协助任务。")
        if not s["commitments"] or s["commitments"][0]["status"] != "active":
            return fail("请先通过确认按钮接受归还承诺。")
        item["owner"] = "player"
        result = "备用钥匙已交给玩家。"
        event(s, "borrow", result, [npc])
    elif kind == "repair":
        if npc != "mechanic" or s["items"]["key"]["owner"] != "player" or s["repaired"]:
            return fail("需持有备用钥匙，在维修员处完成尚未完成的维修。")
        s["repaired"] = True
        # tick below consumes the repair turn, leaving one effective turn to return.
        s["commitments"][0]["due_round"] = s["round"] + 2
        result = "配电箱已修好。下一次有效行动结束前请归还钥匙。"
        e = event(s, "repair", result, [npc])
        add_trust(s, npc, e, "assistance", 5)
    elif kind == "return_item":
        if npc != "owner" or target != "key" or s["items"]["key"]["owner"] != "player":
            return fail("玩家没有可归还给此角色的钥匙。")
        s["items"]["key"]["owner"] = npc
        c = s["commitments"][0]
        result = "备用钥匙已归还店主。"
        e = event(s, "return", result, [npc])
        if c["status"] == "active" and s["repaired"]:
            c["status"] = "fulfilled"
            add_trust(s, npc, e, "promise_fulfilled", 10)
        elif c["status"] != "active":
            c["status"] = "returned_late"
    elif kind == "notify":
        e = next((e for e in s["events"] if e["id"] == target), None)
        if not e or not e["valid"] or e["kind"] not in {"repair", "breach", "return"}:
            return fail("没有可核实的通知依据。")
        if not learn_event(s, npc, e, "player"):
            return fail("该角色已经获知这件事。")
        if e["kind"] == "breach" and npc == "owner":
            add_trust(s, npc, e, "promise_breached", -15)
        result = "已向角色传达可核实事件，并记录获知时间。"
    elif kind == "reveal":
        clue = s["scene"]["clues"].get(target)
        if not clue or clue["source"] != npc or target in s["player_clues"]:
            return fail("没有可以提供的新线索。")
        if target == "maintenance" and not s["repaired"]:
            return fail("维修记录需要修复配电箱后核对。")
        s["player_clues"].append(target)
        result = "获得线索：" + clue["text"]
        event(s, "reveal", result, [npc])
    elif kind == "share":
        clue = s["scene"]["clues"].get(target)
        if target not in s["player_clues"] or not clue:
            return fail("玩家尚未取得该线索。")
        if any(k["npc_id"] == npc and k["id"] == target for k in s["knowledge"]):
            return fail("角色已经知道这条线索。")
        s["knowledge"].append(
            {
                "id": target,
                "npc_id": npc,
                "text": clue["text"],
                "source": clue["source"],
                "speaker": "player",
                "verified": False,
                "learned_at": now(),
                "event_id": None,
            }
        )
        event(s, "share", f"玩家转述了来自{clue['source']}的线索：{clue['text']}", [npc])
        result = "已定向转述；接收者记录原始来源，不因此增减信任。"
    elif kind == "conclude":
        if len(s["player_clues"]) != len(s["scene"]["clues"]) or s["ending"]:
            return fail("请先取得三位角色的线索。")
        s["ending"] = s["scene"]["ending"]
        result = s["ending"]
        event(s, "conclude", "玩家完成了入住记录异常调查。", [npc])
    else:
        return fail("不支持的行动。")
    tick(s)
    return {"ok": True, "message": result}


def available_actions(s):
    actions = []

    def add(npc, kind, label, target=""):
        actions.append({"npc_id": npc, "kind": kind, "target": target, "label": label})

    for task in s["tasks"].values():
        if not task["done"]:
            add(task["npc_id"], "assist", task["title"], task["id"])
    if not s["commitments"] and not s["repaired"]:
        add("owner", "confirm_promise", "确认承诺：维修后的下一行动结束前归还钥匙")
    if (
        s["items"]["key"]["owner"] == "owner"
        and s["commitments"]
        and s["commitments"][0]["status"] == "active"
    ):
        add("owner", "borrow", "请求借用备用钥匙（需信任60）", "key")
    if s["items"]["key"]["owner"] == "player":
        add("owner", "return_item", "归还备用钥匙", "key")
        if not s["repaired"]:
            add("mechanic", "repair", "与维修员修复配电箱")
    for cid, clue in s["scene"]["clues"].items():
        if cid not in s["player_clues"] and (cid != "maintenance" or s["repaired"]):
            add(clue["source"], "reveal", "询问并记录线索", cid)
    for npc in s["npcs"]:
        known = {k["id"] for k in s["knowledge"] if k["npc_id"] == npc}
        for cid in s["player_clues"]:
            if cid not in known:
                add(npc, "share", "转述线索：" + s["scene"]["clues"][cid]["title"], cid)
        for e in s["events"]:
            if e["valid"] and e["kind"] in {"repair", "breach", "return"} and e["id"] not in known:
                add(npc, "notify", "告知：" + e["text"], e["id"])
        if len(s["player_clues"]) == 3 and not s["ending"]:
            add(npc, "conclude", "整理三条线索，完成调查")
    return actions


def player_view(s):
    return copy.deepcopy(
        {
            "id": s["id"],
            "version": s["version"],
            "round": s["round"],
            "scene": {k: s["scene"][k] for k in ("title", "intro")},
            "npcs": [
                {k: n[k] for k in ("id", "name", "role", "description", "trust")}
                for n in s["npcs"].values()
            ],
            "messages": s["messages"],
            "clues": [{"id": cid, **s["scene"]["clues"][cid]} for cid in s["player_clues"]],
            "inventory": [
                {"id": i["id"], "name": i["name"]}
                for i in s["items"].values()
                if i["owner"] == "player"
            ],
            "commitments": s["commitments"],
            "tasks": list(s["tasks"].values()),
            "available_actions": available_actions(s),
            "ending": s["ending"],
        }
    )


def build_context(s, npc, query, memory_enabled=True, budget=12000, retriever=None):
    """Budget is Unicode characters, not tokenizer tokens; trace reports actual input."""
    if npc not in s["npcs"]:
        raise ValueError("角色不存在")
    invalid = {e["id"] for e in s["events"] if not e["valid"]}
    # Historical events only enter through retrieval, never via a backdoor global state dump.
    # Knowing a clue does not grant permission to disclose it. Its body enters dialogue
    # only after a validated reveal has also recorded it in the player's notebook.
    knowledge = [
        k
        for k in s["knowledge"]
        if k["npc_id"] == npc
        and k["event_id"] is None
        and (k["id"] not in s["scene"]["clues"] or k["id"] in s["player_clues"])
    ]
    from app.memory import lexical_rank

    # No unscoped memory is ever passed to an embedding model or its cache.
    authorized = [m for m in s["memories"] if m["npc_id"] == npc and m["event_id"] not in invalid]
    retrieval = {
        "retrieval_strategy": "lexical" if memory_enabled else "disabled",
        "fallback_reason": None,
    }
    if retriever is not None and memory_enabled:
        candidates, retrieval = retriever.rank(authorized, query, s["round"], s["scene"]["aliases"])
    else:
        candidates = lexical_rank(authorized, query, s["round"], s["scene"]["aliases"])
    selected = candidates[:6] if memory_enabled else []
    history = [m for m in s["messages"] if m["npc_id"] == npc]
    rounds = sorted({m["round"] for m in history})[-8:]
    history = [m for m in history if m["round"] in rounds]
    # Action candidates must not reveal events the NPC has not yet learned.
    known_ids = {k["id"] for k in s["knowledge"] if k["npc_id"] == npc}
    actions = [
        a
        for a in available_actions(s)
        if a["npc_id"] == npc and a["kind"] not in {"notify", "confirm_promise"}
    ]
    payload = {
        "role": s["npcs"][npc],
        "scene": s["scene"]["intro"],
        "knowledge": knowledge,
        "memories": selected,
        "history": history,
        "actions": actions,
        "player_input": query,
    }

    # No trusted text is assembled from debug data or another NPC's history.
    def context_size():
        return len(json.dumps(payload, ensure_ascii=False))

    dropped_knowledge, size = [], context_size()
    while size > budget and selected:
        selected.pop()
        size = context_size()
    while size > budget and history:
        history.pop(0)
        size = context_size()
    # A character's own facts are dropped last: an over-budget turn must degrade
    # instead of failing, and the trace still shows what was left out.
    while size > budget and knowledge:
        dropped_knowledge.append(knowledge.pop()["id"])
        size = context_size()
    if size > budget:
        raise ContextBudgetError("当前输入超过上下文预算，请缩短文本。", size=size, budget=budget)
    trace = {
        **retrieval,
        "npc_id": npc,
        "session_id": s["id"],
        "candidates": candidates,
        "selected_ids": [m["id"] for m in selected],
        "history_ids": [m["id"] for m in history],
        "dropped_knowledge_ids": dropped_knowledge,
        "memory_enabled": memory_enabled,
        "context_chars": size,
        "known_ids": sorted(known_ids),
        "context": copy.deepcopy(payload),
    }
    return payload, trace
