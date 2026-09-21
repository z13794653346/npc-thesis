import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agents import DIALOGUE_VERSION, NpcAgent
from app.game import (
    apply_action,
    available_actions,
    message,
    new_state,
    player_view,
    tick,
)
from app.llm import DeepSeek, ModelError
from app.storage import Conflict, Store

ROOT = Path(__file__).resolve().parent.parent
ActionKind = Literal[
    "assist",
    "confirm_promise",
    "borrow",
    "repair",
    "return_item",
    "notify",
    "share",
    "reveal",
    "conclude",
]


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: ActionKind
    target: str = Field(default="", max_length=100)
    evidence_id: str | None = Field(default=None, max_length=100)


class Interaction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    npc_id: Literal["owner", "mechanic", "traveler"]
    text: str = Field(min_length=1, max_length=2000)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    npc_id: Literal["owner", "mechanic", "traveler"]
    action: Action


class ModelOutput(BaseModel):
    """Legacy experiment output; never consumed by the production dialogue route."""

    model_config = ConfigDict(extra="forbid", strict=True)
    reply: str = Field(min_length=1, max_length=4000)
    action: Action | None
    evidence_ids: list[str] = Field(max_length=30)


class GroundingReview(BaseModel):
    """Legacy review baseline used only by the opt-in experiment script."""

    model_config = ConfigDict(extra="forbid", strict=True)
    supported: bool
    unsupported_claims: list[str] = Field(max_length=30)


def redact(value, key=""):
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if (
                    k.lower()
                    in {
                        "api_key",
                        "authorization",
                        "token",
                        "access_token",
                        "refresh_token",
                        "debug_token",
                        "npc_debug_token",
                    }
                    or k.lower().endswith("_api_key")
                )
                else redact(v, key)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        if key:
            value = value.replace(key, "[REDACTED]")
        value = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
        value = re.sub(r"Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value, flags=re.IGNORECASE)
    return value


def create_app(db_path=None, model=None, debug_token=None):
    load_dotenv(ROOT / ".env", override=False)
    path = db_path or os.getenv("NPC_DB_PATH", "data/npc.sqlite3")
    if not Path(path).is_absolute():
        path = ROOT / path
    store = Store(path)
    llm = model if model is not None else DeepSeek()
    if debug_token is None:
        debug_token = (
            os.getenv("NPC_DEBUG_TOKEN", "")
            if os.getenv("NPC_DEBUG", "false").lower() == "true"
            else ""
        )
    app = FastAPI(title="NPC记忆与信任交互系统", version="0.2.0")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver", "[::1]"]
    )
    app.state.store = store

    @app.middleware("http")
    async def local_origin_guard(request, call_next):
        origin = request.headers.get("origin")
        # Same-origin production and the local development UI only. No wildcard CORS.
        if origin and origin not in {
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }:
            return JSONResponse({"detail": "不接受外部站点请求。"}, status_code=403)
        return await call_next(request)

    def read(sid):
        try:
            return store.get(sid)
        except KeyError:
            raise HTTPException(404, "存档不存在。") from None

    def debug_guard(token):
        if not debug_token:
            raise HTTPException(404, "调试功能未开启。")
        if not secrets.compare_digest(token or "", debug_token):
            raise HTTPException(403, "调试口令不正确。")

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "model_configured": llm.configured,
            "model": llm.model,
            "debug_enabled": bool(debug_token),
            "dialogue_version": DIALOGUE_VERSION,
        }

    @app.post("/api/sessions")
    def create_session():
        s = new_state()
        store.create(s)
        return player_view(s)

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        return player_view(read(sid))

    @app.post("/api/sessions/{sid}/reset")
    def reset_session(sid: str):
        read(sid)
        return create_session()

    async def execute(sid, body, direct=False):
        started = time.monotonic()

        async def model_call(context):
            remaining = getattr(llm, "timeout", 30) - (time.monotonic() - started)
            async with asyncio.timeout(max(0, remaining)):
                return await llm.complete(context)

        rid, npc = body.request_id, body.npc_id
        fingerprint = hashlib.sha256(
            json.dumps({"direct": direct, **body.model_dump()}, sort_keys=True).encode()
        ).hexdigest()
        try:
            s, previous, status = store.reserve(sid, rid, fingerprint)
        except KeyError:
            raise HTTPException(404, "存档不存在。") from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        if previous is not None:
            return JSONResponse(previous, status_code=status)
        if status == 202:
            return JSONResponse(
                {
                    "request_id": rid,
                    "status": "processing",
                    "reply": "请求处理中，请稍候。",
                    "action_result": None,
                    "state": player_view(s),
                    "error": None,
                },
                status_code=202,
            )
        expected = s["version"]
        trace = {
            "model": llm.model if not direct else None,
            "mode": "model" if not direct else "rules",
            "scene_version": s["scene"]["version"],
        }
        try:
            if s.get("dialogue_version") != DIALOGUE_VERSION:
                raise ModelError(
                    "legacy_session",
                    "这是旧版本存档，仅供查看。请点击新游戏使用三个NPC Agent；旧存档不会删除。",
                )
            if direct:
                action = body.action.model_dump()
                reply = ""
                label = next(
                    (
                        a["label"]
                        for a in available_actions(s)
                        if a["npc_id"] == npc
                        and a["kind"] == action["kind"]
                        and a["target"] == action["target"]
                    ),
                    "提交操作请求",
                )
                user_text = "[操作] " + label
            else:
                user_text = body.text
                agent = NpcAgent.restore(s, npc, user_text)
                context = agent.context
                trace["retrieval"] = agent.trace
                trace["agent_id"] = npc
                trace["dialogue_version"] = DIALOGUE_VERSION
                raw = await model_call(context)
                trace["raw_output"] = raw
                reply, action, decision = agent.resolve(raw)
                trace["decision"] = decision
            outcome = None
            trace["proposed_action"] = action
            if action:
                if not direct and action["kind"] == "confirm_promise":
                    outcome = {"ok": False, "message": "承诺需要你点击确认按钮，尚未自动接受。"}
                elif not direct and not any(
                    a["kind"] == action["kind"] and a["target"] == action["target"]
                    for a in context["actions"]
                ):
                    outcome = {"ok": False, "message": "该行动不在角色本次可用操作中，未执行。"}
                else:
                    outcome = apply_action(s, npc, action)
                # Pre-execution prose is not an account of what actually happened.
                # Keep it in the debug trace, never in the player's reply or history.
                reply = outcome["message"]
            else:
                tick(s)
            trace["action_result"] = outcome
            message(s, npc, "player", user_text)
            message(s, npc, "system" if direct else "npc", reply)
            s["messages"][-1].update(
                {
                    "agent_id": npc,
                    "dialogue_version": DIALOGUE_VERSION,
                    "evidence_ids": [] if direct else decision["evidence_ids"],
                }
            )
            s["version"] = expected + 1
            result = {
                "request_id": rid,
                "status": "completed",
                "reply": reply,
                "action_result": outcome,
                "state": player_view(s),
                "error": None,
            }
            trace["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
            store.commit(s, expected, rid, result, redact(trace, getattr(llm, "api_key", "")))
            return result
        except (
            ModelError,
            ValidationError,
            ValueError,
            TimeoutError,
            sqlite3.Error,
            Conflict,
        ) as exc:
            code = getattr(exc, "code", "invalid_output")
            explanation = "模型输出格式不符合要求，本次未执行。"
            http_status = 200
            if isinstance(exc, ModelError):
                explanation = str(exc)
            elif isinstance(exc, Conflict):
                code, explanation, http_status = "state_conflict", str(exc), 409
            elif isinstance(exc, sqlite3.Error):
                code, explanation = "storage_error", "存储提交失败，本次游戏状态未改变。"
            elif isinstance(exc, TimeoutError):
                code, explanation = "model_timeout", "模型请求超时，本次未执行。"
            result = {
                "request_id": rid,
                "status": "failed",
                "reply": explanation,
                "action_result": None,
                "state": player_view(read(sid)),
                "error": {"code": code, "message": explanation},
            }
            trace.update(
                {"error": code, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}
            )
            try:
                store.fail(
                    sid, rid, result, redact(trace, getattr(llm, "api_key", "")), http_status
                )
            except sqlite3.Error:
                pass  # Database unavailable; do not expose DB paths or raw errors.
            return JSONResponse(result, status_code=http_status)

    @app.post("/api/sessions/{sid}/interactions")
    async def interact(sid: str, body: Interaction):
        return await execute(sid, body)

    @app.post("/api/sessions/{sid}/actions")
    async def act(sid: str, body: ActionRequest):
        return await execute(sid, body, direct=True)

    @app.get("/api/sessions/{sid}/debug")
    def debug(sid: str, x_debug_token: str | None = Header(default=None)):
        debug_guard(x_debug_token)
        read(sid)
        return redact(store.debug(sid), getattr(llm, "api_key", ""))

    @app.get("/api/sessions/{sid}/export")
    def export(sid: str, x_debug_token: str | None = Header(default=None)):
        debug_guard(x_debug_token)
        read(sid)
        return JSONResponse(
            redact(store.debug(sid), getattr(llm, "api_key", "")),
            headers={"Content-Disposition": 'attachment; filename="npc-session.json"'},
        )

    frontend = ROOT / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
