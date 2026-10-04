import asyncio
import copy

import pytest

from app.game import new_state
from app.llm import ModelError


def test_graph_validates_decision_without_mutating_game():
    from app.workflow import NpcWorkflow

    state = new_state()
    before = copy.deepcopy(state)
    calls = []

    async def model_call(context):
        calls.append(context)
        return {"intent": "intro", "evidence_ids": [], "action_id": None}

    result = asyncio.run(NpcWorkflow().decide(state, "owner", "你好", model_call))
    assert state == before
    assert len(calls) == 1
    assert "林掌柜" in result["reply"]
    assert result["action"] is None
    assert [step["node"] for step in result["workflow_trace"]] == [
        "restore", "decide", "validate"
    ]
    assert all(step["elapsed_ms"] >= 0 for step in result["workflow_trace"])
    assert "game_state" not in result


def test_graph_rejects_unauthorized_fact_and_never_retries_model():
    from app.workflow import NpcWorkflow

    state = new_state()
    before = copy.deepcopy(state)
    calls = []

    async def model_call(context):
        calls.append(context)
        return {"intent": "answer", "evidence_ids": ["other-npc-secret"], "action_id": None}

    with pytest.raises(ModelError):
        asyncio.run(NpcWorkflow().decide(state, "owner", "秘密", model_call))
    assert len(calls) == 1
    assert state == before


def test_compiled_graph_keeps_concurrent_requests_isolated():
    from app.workflow import NpcWorkflow

    workflow = NpcWorkflow()
    state = new_state()

    async def model_call(context):
        await asyncio.sleep(0)
        return {"intent": "intro", "evidence_ids": [], "action_id": None}

    async def run():
        return await asyncio.gather(
            workflow.decide(state, "owner", "你好", model_call),
            workflow.decide(state, "mechanic", "你好", model_call),
        )

    owner, mechanic = asyncio.run(run())
    assert "林掌柜" in owner["reply"] and "周衡" in mechanic["reply"]
    assert owner["context"]["agent_id"] == "owner"
    assert mechanic["context"]["agent_id"] == "mechanic"


def test_game_snapshot_is_not_sent_to_external_tracing():
    from langsmith import get_tracing_context, tracing_context

    from app.workflow import NpcWorkflow

    async def model_call(context):
        assert get_tracing_context()["enabled"] is False
        return {"intent": "intro", "evidence_ids": [], "action_id": None}

    with tracing_context(enabled=True):
        asyncio.run(NpcWorkflow().decide(new_state(), "owner", "你好", model_call))
        assert get_tracing_context()["enabled"] is True
