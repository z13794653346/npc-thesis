"""LangGraph computes decisions; Store remains the sole game commit boundary."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.agents import NpcAgent


class Turn(TypedDict, total=False):
    snapshot: dict
    npc_id: str
    query: str
    model_call: Callable[[dict], Awaitable[dict]]
    retriever: Any
    agent: NpcAgent
    raw_output: dict
    reply: str
    action: dict | None
    decision: dict
    workflow_trace: list[dict]
    request_trace: dict | None


def step(turn, node, started):
    steps = turn.get("workflow_trace", []) + [
        {"node": node, "elapsed_ms": round((time.monotonic() - started) * 1000, 3)}
    ]
    if turn.get("request_trace") is not None:
        turn["request_trace"]["workflow_trace"] = steps
    return steps


class NpcWorkflow:
    def __init__(self):
        graph = StateGraph(Turn)
        graph.add_node("restore", self.restore)
        graph.add_node("decide", self.model_decision)
        graph.add_node("validate", self.validate)
        graph.add_edge(START, "restore")
        graph.add_edge("restore", "decide")
        graph.add_edge("decide", "validate")
        graph.add_edge("validate", END)
        # No checkpointer: in-flight snapshots are never a second persistent save.
        self.graph = graph.compile()

    @staticmethod
    async def restore(turn):
        started = time.monotonic()
        options = {"retriever": turn["retriever"]} if turn.get("retriever") else {}
        agent = await asyncio.to_thread(
            NpcAgent.restore, turn["snapshot"], turn["npc_id"], turn["query"], **options
        )
        if turn.get("request_trace") is not None:
            turn["request_trace"].update(
                retrieval=agent.trace,
                agent_id=agent.npc_id,
                dialogue_version=agent.context["dialogue_version"],
            )
        return {"agent": agent, "workflow_trace": step(turn, "restore", started)}

    @staticmethod
    async def model_decision(turn):
        started = time.monotonic()
        raw = await turn["model_call"](turn["agent"].context)
        if turn.get("request_trace") is not None:
            turn["request_trace"]["raw_output"] = raw
        return {"raw_output": raw, "workflow_trace": step(turn, "decide", started)}

    @staticmethod
    def validate(turn):
        started = time.monotonic()
        reply, action, decision = turn["agent"].resolve(turn["raw_output"])
        return {
            "reply": reply,
            "action": action,
            "decision": decision,
            "workflow_trace": step(turn, "validate", started),
        }

    async def decide(self, state, npc_id, query, model_call, retriever=None, trace=None):
        # The sink belongs to this request only. Completed stages survive errors;
        # it is redacted by the API before storage and never kept on this instance.
        if trace is not None:
            trace.update(orchestrator="langgraph", workflow_trace=[])
        # Raw game snapshots stay local even if global tracing is configured.
        with tracing_context(enabled=False):
            turn = await self.graph.ainvoke(
                {
                    "snapshot": state,
                    "npc_id": npc_id,
                    "query": query,
                    "model_call": model_call,
                    "retriever": retriever,
                    "workflow_trace": [],
                    "request_trace": trace,
                }
            )
        agent = turn["agent"]
        return {
            "reply": turn["reply"],
            "action": turn["action"],
            "decision": turn["decision"],
            "raw_output": turn["raw_output"],
            "context": agent.context,
            "retrieval": agent.trace,
            "workflow_trace": turn["workflow_trace"],
        }
