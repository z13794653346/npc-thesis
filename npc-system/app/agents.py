"""Scoped NPC state views, bounded decisions and deterministic dialogue rendering."""

import copy
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.game import build_context
from app.llm import ModelError

DIALOGUE_VERSION = 2
PROFILES = {
    "owner": {"goal": "根据登记记录和守约情况处理玩家请求", "lead": "先把来源说清楚。"},
    "mechanic": {"goal": "协助维修并提供可披露的维修记录", "lead": "按记录说。"},
    "traveler": {
        "goal": "提供允许披露的见闻并区分转述和已知事实",
        "lead": "我把来源和不确定的部分分开说。",
    },
}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["intro", "answer", "source", "act", "unknown", "clarify"]
    evidence_ids: list[str] = Field(max_length=3)
    action_id: str | None = Field(max_length=150)


class NpcAgent:
    """One session/role snapshot. Durable state lives in the existing SQLite save.

    Instances are rehydrated for the selected NPC per turn, never shared mutable
    process-wide objects. The model receives only a copy of this scoped view.
    """

    @classmethod
    def restore(cls, state, npc_id, query, memory_enabled=True, retriever=None):
        if npc_id not in PROFILES:
            raise ValueError("角色不存在")
        scoped, retrieval = build_context(
            state, npc_id, query, memory_enabled, budget=10000, retriever=retriever
        )
        agent = cls()
        agent.session_id = state["id"]
        agent.npc_id = npc_id
        agent.role = copy.deepcopy(scoped["role"])
        agent._facts = {
            "public:scene": {
                "id": "public:scene",
                "text": state["scene"]["intro"],
                "source": "公开场景",
                "basis": "公开信息",
                "verified": True,
            },
        }
        events = {e["id"]: e for e in state["events"] if e["valid"]}
        names = {n: v["name"] for n, v in state["npcs"].items()}
        for entry in scoped["knowledge"] + scoped["memories"]:
            # A share writes both the semantic clue (with its original source)
            # and an audit event. Only the clue is a fact candidate; exposing the
            # audit event would duplicate the content and leak internal role ids.
            if events.get(entry["id"], {}).get("kind") == "share":
                continue
            source = names.get(entry["source"], "系统记录")
            verified = entry.get("verified", True)
            basis = "已核实事件记录"
            if entry["id"] in state["scene"]["clues"]:
                clue = state["scene"]["clues"][entry["id"]]
                basis = "见闻记录" if entry["id"] == "sighting" else "查阅记录"
                source = names[clue["source"]]
            if not verified:
                verified = False
                basis = "转述记录（未核实）"
            agent._facts[entry["id"]] = {
                "id": entry["id"],
                "text": entry["text"],
                "source": source,
                "basis": basis,
                "verified": verified,
            }
        agent._facts = copy.deepcopy(agent._facts)
        agent._actions = {
            a["kind"] + ":" + a["target"]: {"kind": a["kind"], "target": a["target"]}
            for a in scoped["actions"]
        }
        agent.context = copy.deepcopy(
            {
                "task": "npc_decision",
                "dialogue_version": DIALOGUE_VERSION,
                "agent_id": npc_id,
                "role": agent.role,
                "goal": PROFILES[npc_id]["goal"],
                "facts": list(agent._facts.values()),
                "actions": [{"id": a["kind"] + ":" + a["target"], **a} for a in scoped["actions"]],
                "history": scoped["history"],
                "player_input": query,
            }
        )
        chars = len(json.dumps(agent.context, ensure_ascii=False))
        if chars > 12000:
            raise ValueError("当前输入超过上下文预算，请缩短文本。")
        agent.trace = {
            **retrieval,
            "agent_id": npc_id,
            "dialogue_version": DIALOGUE_VERSION,
            "context": copy.deepcopy(agent.context),
            "context_chars": chars,
        }
        return agent

    def resolve(self, raw):
        choice = Decision.model_validate(raw)
        ids = choice.evidence_ids
        if len(ids) != len(set(ids)):
            raise ModelError("invalid_evidence", "不能重复引用同一条依据，本次未执行。")
        if not set(ids) <= self._facts.keys():
            raise ModelError("invalid_evidence", "角色无法访问所选依据，本次未执行。")
        if choice.intent == "act":
            if ids or choice.action_id is None:
                raise ModelError("invalid_decision", "行动决策与依据字段不匹配，本次未执行。")
            if choice.action_id not in self._actions:
                raise ModelError("invalid_action", "该行动不在角色本次可用操作中，未执行。")
            return "", copy.deepcopy(self._actions[choice.action_id]), choice.model_dump()
        if choice.action_id is not None:
            raise ModelError("invalid_decision", "非行动回应不能携带动作，本次未执行。")
        if choice.intent in {"answer", "source"}:
            if not ids:
                raise ModelError("invalid_evidence", "事实回应必须选择依据，本次未执行。")
            lines = [PROFILES[self.npc_id]["lead"]]
            for fid in ids:
                fact = self._facts[fid]
                # Never ask a model to paraphrase, infer a witness, or fill a text slot.
                lines.append(f"【{fact['basis']}；来源：{fact['source']}】{fact['text']}")
            reply = "\n".join(lines)
        else:
            if ids:
                raise ModelError("invalid_decision", "此回应类型不能携带事实依据，本次未执行。")
            if choice.intent == "intro":
                reply = f"我是{self.role['name']}，这里的{self.role['role']}。你想问哪件事？"
            elif choice.intent == "clarify":
                reply = "你想询问线索、回忆先前的约定，还是请求一项行动？请说具体一些。"
            else:
                reply = "关于这件事，我目前没有可以提供的确切依据。"
        return reply, None, choice.model_dump()
