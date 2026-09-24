"""Regression: FastAPI lifespan handler runs startup and shutdown.

Migration from @app.on_event('startup')/@app.on_event('shutdown') to a
FastAPI lifespan async-context-manager (both on_event decorators are
deprecated in current FastAPI). Behavior must be identical: Postgres pool
opened before serving, both pool and Redis closed after serving.

TestClient's `with app:` context is what triggers the lifespan enter/exit
— the earlier security-pass tests intentionally used TestClient WITHOUT
the context so they didn't need a real DB. These tests do the opposite:
they patch _wait_for_postgres and redis.Redis with test doubles so the
lifespan can run to completion and the enter/exit sequencing can be
observed.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient


def _import_main(env: dict[str, str]):
    for key in ("main", "code.main"):
        sys.modules.pop(key, None)
    for k in ("API_KEY", "EXPOSE_DOCS"):
        os.environ.pop(k, None)
    for k, v in env.items():
        os.environ[k] = v
    return importlib.import_module("main")


class _FakePool:
    def __init__(self, calls: dict) -> None:
        self._calls = calls

    async def close(self) -> None:
        self._calls["pool_close"] += 1


class _FakeRedis:
    def __init__(self, calls: dict) -> None:
        self._calls = calls

    async def close(self) -> None:
        self._calls["redis_close"] += 1


def test_lifespan_opens_pool_and_redis_on_startup(monkeypatch):
    m = _import_main({"POSTGRES_PASSWORD": "notweak"})
    calls: dict[str, int] = {"pool_open": 0, "pool_close": 0, "redis_close": 0}

    async def fake_wait(*_a, **_kw):
        calls["pool_open"] += 1
        return _FakePool(calls)

    monkeypatch.setattr(m, "_wait_for_postgres", fake_wait)
    monkeypatch.setattr(m.redis, "Redis", lambda **_kw: _FakeRedis(calls))

    # Enter the lifespan by using TestClient as a context manager.
    with TestClient(m.app) as client:
        assert calls["pool_open"] == 1, "startup did not open the pool"
        assert m.db_pool is not None, "startup did not populate module global db_pool"
        assert m.redis_client is not None, "startup did not populate module global redis_client"
        # Prove a request routes through the fully-initialised app.
        r = client.get("/healthz")
        assert r.status_code == 200

    # Post-exit: shutdown must have closed both.
    assert calls["pool_close"] == 1, "shutdown did not close the pool"
    assert calls["redis_close"] == 1, "shutdown did not close the redis client"


def test_lifespan_shutdown_closes_even_if_endpoint_raised(monkeypatch):
    """A raised endpoint (e.g., 500) must not skip lifespan teardown."""
    m = _import_main({"POSTGRES_PASSWORD": "notweak"})
    calls = {"pool_close": 0, "redis_close": 0}

    async def fake_wait(*_a, **_kw):
        return _FakePool(calls)

    monkeypatch.setattr(m, "_wait_for_postgres", fake_wait)
    monkeypatch.setattr(m.redis, "Redis", lambda **_kw: _FakeRedis(calls))

    with TestClient(m.app) as client:
        # Hit a non-existent route; FastAPI 404s but lifespan still runs.
        r = client.get("/nope-does-not-exist")
        assert r.status_code == 404

    assert calls["pool_close"] == 1
    assert calls["redis_close"] == 1


def test_startup_failure_surfaces(monkeypatch):
    """If _wait_for_postgres raises (as it will on weak POSTGRES_PASSWORD),
    the lifespan enter must fail loudly, not swallow. TestClient's `with`
    context re-raises the startup error — proof that the vector-3 refusal
    survives the on_event → lifespan migration."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    m = _import_main({})
    with (
        pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"),
        TestClient(m.app),
    ):
        pass


def test_module_globals_reset_after_shutdown(monkeypatch):
    """db_pool and redis_client are set to None on shutdown so a subsequent
    lifespan cycle starts clean rather than inheriting a closed handle."""
    m = _import_main({"POSTGRES_PASSWORD": "notweak"})
    calls = {"pool_close": 0, "redis_close": 0}

    async def fake_wait(*_a, **_kw):
        return _FakePool(calls)

    monkeypatch.setattr(m, "_wait_for_postgres", fake_wait)
    monkeypatch.setattr(m.redis, "Redis", lambda **_kw: _FakeRedis(calls))

    with TestClient(m.app):
        pass

    assert m.db_pool is None
    assert m.redis_client is None
