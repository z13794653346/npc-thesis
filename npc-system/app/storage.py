"""SQLite snapshot + request ledger. All game mutations commit as one transaction."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL,
                    result TEXT, trace TEXT, http_status INTEGER NOT NULL DEFAULT 200,
                    PRIMARY KEY(session_id, request_id)
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, state):
        with self.connection() as db:
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (state["id"], state["version"], json.dumps(state, ensure_ascii=False)),
            )

    def get(self, sid):
        with self.connection() as db:
            row = db.execute("SELECT state FROM sessions WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise KeyError(sid)
            return json.loads(row["state"])

    def reserve(self, sid, rid, fingerprint):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM sessions WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise KeyError(sid)
            prior = db.execute(
                "SELECT * FROM requests WHERE session_id=? AND request_id=?", (sid, rid)
            ).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise Conflict("同一请求编号不能用于不同内容。")
                if prior["result"]:
                    return (
                        json.loads(row["state"]),
                        json.loads(prior["result"]),
                        prior["http_status"],
                    )
                if time.time() - prior["created"] > 120:
                    # Never retry an expired claim with the same key: the old worker may live.
                    raise Conflict("该请求已过期，请使用新的请求编号重试。")
                return json.loads(row["state"]), None, 202
            db.execute(
                "INSERT INTO requests(session_id,request_id,fingerprint,status,created) VALUES(?,?,?,?,?)",
                (sid, rid, fingerprint, "processing", time.time()),
            )
            return json.loads(row["state"]), None, 0

    def commit(self, state, expected_version, rid, result, trace):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE sessions SET version=?,state=? WHERE id=? AND version=?",
                (
                    state["version"],
                    json.dumps(state, ensure_ascii=False),
                    state["id"],
                    expected_version,
                ),
            ).rowcount
            if changed != 1:
                raise Conflict("状态已被另一操作更新，本次未执行，请重试。")
            db.execute(
                "UPDATE requests SET status=?,result=?,trace=?,http_status=200 WHERE session_id=? AND request_id=?",
                (
                    result["status"],
                    json.dumps(result, ensure_ascii=False),
                    json.dumps(trace, ensure_ascii=False),
                    state["id"],
                    rid,
                ),
            )

    def fail(self, sid, rid, result, trace, http_status=200):
        with self.connection() as db:
            db.execute(
                "UPDATE requests SET status='failed',result=?,trace=?,http_status=? WHERE session_id=? AND request_id=?",
                (
                    json.dumps(result, ensure_ascii=False),
                    json.dumps(trace, ensure_ascii=False),
                    http_status,
                    sid,
                    rid,
                ),
            )

    def debug(self, sid):
        state = self.get(sid)
        with self.connection() as db:
            rows = db.execute(
                "SELECT request_id,status,created,trace FROM requests WHERE session_id=? ORDER BY created",
                (sid,),
            )
            return {
                "state": state,
                "requests": [{**dict(r), "trace": json.loads(r["trace"] or "{}")} for r in rows],
            }
