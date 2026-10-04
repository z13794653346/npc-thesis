"""ORM snapshot + request ledger. Game mutations commit in one transaction."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db_models import Base, GameSession, Request


class Conflict(Exception):
    pass


class StorageError(Exception):
    """Database failure, independent of the configured backend."""


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def normalize_database_url(value):
    """Use the installed PostgreSQL driver when a URL leaves it unspecified."""
    url = make_url(value)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url


class Store:
    def __init__(self, path):
        self.path = str(path)
        url = normalize_database_url(self.path if "://" in self.path else "sqlite:///" + self.path)
        if url.get_backend_name() not in {"sqlite", "postgresql"}:
            raise ValueError("Only SQLite and PostgreSQL are supported.")
        options = {}
        if url.get_backend_name() == "sqlite":
            if url.database and url.database != ":memory:":
                Path(url.database).parent.mkdir(parents=True, exist_ok=True)
            options["connect_args"] = {"timeout": 5, "check_same_thread": False}
            if url.database in {None, "", ":memory:"}:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self._sqlite = self.engine.dialect.name == "sqlite"
        if self._sqlite:

            @event.listens_for(self.engine, "connect")
            def configure_sqlite(db, record):
                cursor = db.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        try:
            if self._sqlite:
                with self.engine.connect() as db:
                    db.exec_driver_sql("PRAGMA journal_mode=WAL")
            Base.metadata.create_all(self.engine)
        except SQLAlchemyError as exc:
            raise StorageError("Database initialization failed.") from exc

    @contextmanager
    def connection(self):
        """Maintenance interface; SQLite retains its native SQL API."""
        if not self._sqlite:
            with self.engine.begin() as db:
                yield db
            return
        db = self.engine.raw_connection()
        db.driver_connection.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.driver_connection.row_factory = None
            db.close()

    @contextmanager
    def _transaction(self, *, write=False):
        try:
            with Session(self.engine) as db, db.begin():
                if write and self._sqlite:
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                yield db
        except SQLAlchemyError as exc:
            raise StorageError("Database operation failed.") from exc

    def create(self, state):
        with self._transaction(write=True) as db:
            db.add(GameSession(id=state["id"], version=state["version"], state=dumps(state)))

    def get(self, sid):
        with self._transaction() as db:
            row = db.get(GameSession, sid)
            if row is None:
                raise KeyError(sid)
            return json.loads(row.state)

    def reserve(self, sid, rid, fingerprint):
        with self._transaction(write=True) as db:
            query = select(GameSession).where(GameSession.id == sid)
            if not self._sqlite:
                query = query.with_for_update()
            row = db.scalar(query)
            if row is None:
                raise KeyError(sid)
            prior = db.get(Request, (sid, rid))
            if prior:
                if prior.fingerprint != fingerprint:
                    raise Conflict("同一请求编号不能用于不同内容。")
                if prior.result:
                    return json.loads(row.state), json.loads(prior.result), prior.http_status
                if time.time() - prior.created > 120:
                    raise Conflict("该请求已过期，请使用新的请求编号重试。")
                return json.loads(row.state), None, 202
            db.add(
                Request(
                    session_id=sid,
                    request_id=rid,
                    fingerprint=fingerprint,
                    status="processing",
                    created=time.time(),
                )
            )
            return json.loads(row.state), None, 0

    def commit(self, state, expected_version, rid, result, trace):
        with self._transaction(write=True) as db:
            changed = db.execute(
                update(GameSession)
                .where(GameSession.id == state["id"], GameSession.version == expected_version)
                .values(version=state["version"], state=dumps(state))
            ).rowcount
            if changed != 1:
                raise Conflict("状态已被另一操作更新，本次未执行，请重试。")
            db.execute(
                update(Request)
                .where(Request.session_id == state["id"], Request.request_id == rid)
                .values(
                    status=result["status"],
                    result=dumps(result),
                    trace=dumps(trace),
                    http_status=200,
                )
            )

    def fail(self, sid, rid, result, trace, http_status=200):
        with self._transaction(write=True) as db:
            db.execute(
                update(Request)
                .where(Request.session_id == sid, Request.request_id == rid)
                .values(
                    status="failed",
                    result=dumps(result),
                    trace=dumps(trace),
                    http_status=http_status,
                )
            )

    def debug(self, sid):
        state = self.get(sid)
        with self._transaction() as db:
            rows = db.scalars(
                select(Request).where(Request.session_id == sid).order_by(Request.created)
            )
            return {
                "state": state,
                "requests": [
                    {
                        "request_id": row.request_id,
                        "status": row.status,
                        "created": row.created,
                        "trace": json.loads(row.trace or "{}"),
                    }
                    for row in rows
                ],
            }
