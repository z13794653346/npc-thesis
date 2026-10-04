import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.storage import Conflict, Store


def test_orm_engine_and_reservation_concurrency(tmp_path):
    store = Store(tmp_path / "race.sqlite")
    assert store.engine.dialect.name == "sqlite"
    store.create({"id": "s", "version": 0})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.reserve("s", "r", "same"), range(4)))
    assert sorted(r[2] for r in results) == [0, 202, 202, 202]
    with pytest.raises(Conflict):
        store.reserve("s", "r", "different")


def test_commit_rolls_back_request_and_state(tmp_path):
    from app.storage import StorageError

    store = Store(tmp_path / "rollback.sqlite")
    state = {"id": "s", "version": 0}
    store.create(state)
    store.reserve("s", "r", "same")
    with store.connection() as db:
        db.execute(
            "CREATE TRIGGER reject_request BEFORE UPDATE ON requests BEGIN SELECT RAISE(FAIL, 'injected'); END"
        )
    with pytest.raises(StorageError):
        store.commit({"id": "s", "version": 1}, 0, "r", {"status": "ok"}, {})
    assert store.get("s") == state
    assert store.reserve("s", "r", "same")[2] == 202


def test_stale_commit_cannot_overwrite(tmp_path):
    store = Store(tmp_path / "stale.sqlite")
    store.create({"id": "s", "version": 0})
    store.reserve("s", "first", "a")
    store.reserve("s", "second", "b")
    store.commit({"id": "s", "version": 1}, 0, "first", {"status": "ok"}, {})
    with pytest.raises(Conflict):
        store.commit({"id": "s", "version": 1, "bad": True}, 0, "second", {"status": "ok"}, {})
    assert "bad" not in store.get("s")


def test_unstamped_legacy_migration_roundtrip_preserves_data(tmp_path):
    from alembic import command
    from alembic.config import Config

    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL); CREATE TABLE requests (session_id TEXT NOT NULL REFERENCES sessions(id), request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, result TEXT, trace TEXT, http_status INTEGER NOT NULL DEFAULT 200, PRIMARY KEY(session_id, request_id));"
        )
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)", ("s", 0, json.dumps({"id": "s", "version": 0}))
        )
        db.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s", "r", "f", "done", 1.0, '{"status":"ok"}', "{}", 200),
        )
        before = db.execute("SELECT * FROM requests").fetchall()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM requests").fetchall() == before
    assert Store(path).get("s") == {"id": "s", "version": 0}


def test_sqlite_url_failed_request_replays_status_and_debug(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'url.sqlite'}")
    state = {"id": "s", "version": 0, "name": "中文"}
    store.create(state)
    store.reserve("s", "r", "f")
    store.fail("s", "r", {"status": "failed"}, {"why": "测试"}, http_status=503)
    assert store.reserve("s", "r", "f") == (state, {"status": "failed"}, 503)
    assert store.debug("s")["requests"][0]["trace"] == {"why": "测试"}


def test_migration_creates_empty_database(tmp_path):
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    path = tmp_path / "fresh.sqlite"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0001_snapshot_ledger",
        )
        assert {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } >= {"sessions", "requests"}


def test_concurrent_commits_allow_only_one_version_update(tmp_path):
    store = Store(tmp_path / "commits.sqlite")
    store.create({"id": "s", "version": 0})
    for rid in ("a", "b"):
        store.reserve("s", rid, rid)

    def commit(rid):
        try:
            store.commit({"id": "s", "version": 1, "winner": rid}, 0, rid, {"status": "ok"}, {})
            return "committed"
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, ("a", "b"))) == ["committed", "conflict"]
    assert store.get("s")["version"] == 1
    with store.connection() as db:
        assert (
            db.execute("SELECT count(*) FROM requests WHERE result IS NOT NULL").fetchone()[0] == 1
        )


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg"])
def test_store_uses_psycopg3_for_postgresql_urls(monkeypatch, driver):
    from unittest.mock import Mock

    from app import storage

    captured = []
    engine = Mock()
    engine.dialect.name = "postgresql"

    def create_engine(url, **options):
        captured.append(url)
        return engine

    monkeypatch.setattr(storage, "create_engine", create_engine)
    monkeypatch.setattr(storage.Base.metadata, "create_all", lambda engine: None)
    storage.Store(f"{driver}://demo:p%40ss@localhost:5432/npc?application_name=npc")
    assert captured[0].drivername == "postgresql+psycopg"
    assert captured[0].password == "p@ss"
    assert captured[0].query == {"application_name": "npc"}


def test_alembic_uses_psycopg3_without_connecting(monkeypatch):
    import sqlalchemy
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    class EngineIntercepted(Exception):
        pass

    captured = []

    def intercept_engine(config, **kwargs):
        captured.append(make_url(config["sqlalchemy.url"]))
        raise EngineIntercepted

    monkeypatch.setattr(sqlalchemy, "engine_from_config", intercept_engine)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", "postgresql://demo:p%%40ss@localhost/npc")
    with pytest.raises(EngineIntercepted):
        command.upgrade(config, "head")
    assert captured[0].drivername == "postgresql+psycopg"
    assert captured[0].password == "p@ss"


def test_alembic_database_url_argument_overrides_ini_without_connecting(monkeypatch):
    from argparse import Namespace

    import sqlalchemy
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    class EngineIntercepted(Exception):
        pass

    captured = []

    def intercept_engine(config, **kwargs):
        captured.append(make_url(config["sqlalchemy.url"]))
        raise EngineIntercepted

    monkeypatch.setattr(sqlalchemy, "engine_from_config", intercept_engine)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.cmd_opts = Namespace(x=["database_url=postgresql://demo:p%40ss@localhost/npc"])
    with pytest.raises(EngineIntercepted):
        command.upgrade(config, "head")
    assert captured[0].drivername == "postgresql+psycopg"
    assert captured[0].password == "p@ss"
