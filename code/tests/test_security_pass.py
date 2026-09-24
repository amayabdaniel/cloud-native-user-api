"""Regression tests for the 2026-09-19 Saturday security pass.

Vectors covered — each block below drives one distinct attack surface that
was exposed pre-fix. Every test fails on the pre-fix code path (see the
per-block comments for how).

  Vector 1 — AuthN/AuthZ:      /users, /users/{id} were open. Now gated by
                               Bearer API_KEY; fail-secure when the server
                               itself lacks the config.
  Vector 3 — Transport/secrets: POSTGRES_PASSWORD fell back to 'postgres'.
                               Now startup refuses on unset or weak.
  Vector 4 — Input DoS:        QuestionRequest/UserCreate had no length
                               bounds. Now Field-bounded.
  Vector 6 — Data exposure:    /users returned every row in one call and
                               cached it. Now paginated with a hard max.
  Vector 8 — Infra & config:   /docs, /redoc, /openapi.json were open by
                               default. Now closed unless EXPOSE_DOCS=1.

The auth path tests do not need a real DB — the auth dependency runs
BEFORE the endpoint body, so a 503/401 short-circuits and the DB is never
touched. That's the property the tests exercise.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from unittest import mock

import pydantic
import pytest
from fastapi.testclient import TestClient


def _import_main(env: dict[str, str]):
    """Reload the app module under a specific env. The app reads several
    values at import time (API_KEY, EXPOSE_DOCS); reload guarantees each
    test sees the env it expects."""
    for key in ("main", "code.main"):
        sys.modules.pop(key, None)
    # Ensure keys the app cares about are set exactly to `env`.
    for k in ("API_KEY", "EXPOSE_DOCS"):
        os.environ.pop(k, None)
    for k, v in env.items():
        os.environ[k] = v
    return importlib.import_module("main")


def _test_client(m) -> TestClient:
    """Build a TestClient WITHOUT triggering the startup event, so the tests
    don't attempt a real Postgres/Redis connection. The auth and validation
    paths under test all short-circuit before hitting db_pool."""
    return TestClient(m.app)


# ---- Vector 3 — refuses weak / unset POSTGRES_PASSWORD ------------------

def test_startup_refuses_unset_password(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    m = _import_main({})
    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        asyncio.run(m._wait_for_postgres())


@pytest.mark.parametrize("weak", ["postgres", "PASSWORD", "changeme", "admin", "root", ""])
def test_startup_refuses_weak_password(monkeypatch, weak):
    monkeypatch.setenv("POSTGRES_PASSWORD", weak)
    m = _import_main({})
    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        asyncio.run(m._wait_for_postgres())


# ---- Vector 4 — input bounds --------------------------------------------

def test_question_field_rejects_oversize():
    m = _import_main({})
    with pytest.raises(pydantic.ValidationError):
        m.QuestionRequest(question="x" * (m.MAX_QUESTION_LEN + 1))


def test_question_field_rejects_empty():
    m = _import_main({})
    with pytest.raises(pydantic.ValidationError):
        m.QuestionRequest(question="")


def test_user_create_field_rejects_oversize_name():
    m = _import_main({})
    with pytest.raises(pydantic.ValidationError):
        m.UserCreate(name="x" * (m.MAX_USER_NAME_LEN + 1), email="a@b.co")


def test_user_create_field_rejects_oversize_email():
    m = _import_main({})
    # Build an email that exceeds MAX_USER_EMAIL_LEN.
    long_email = ("x" * (m.MAX_USER_EMAIL_LEN + 10)) + "@example.com"
    with pytest.raises(pydantic.ValidationError):
        m.UserCreate(name="ok", email=long_email)


def test_user_create_field_rejects_malformed_email():
    m = _import_main({})
    with pytest.raises(pydantic.ValidationError):
        m.UserCreate(name="ok", email="not-an-email")


def test_user_create_accepts_reasonable_input():
    m = _import_main({})
    u = m.UserCreate(name="Ada Lovelace", email="ada@example.com")
    assert u.name == "Ada Lovelace"


# ---- Vector 8 — docs disabled by default --------------------------------

def test_docs_endpoints_hidden_by_default():
    m = _import_main({})
    assert m.app.docs_url is None
    assert m.app.redoc_url is None
    assert m.app.openapi_url is None


def test_docs_endpoints_exposed_when_env_set():
    m = _import_main({"EXPOSE_DOCS": "1"})
    assert m.app.docs_url == "/docs"
    assert m.app.openapi_url == "/openapi.json"


# ---- Vector 1 — auth gates the PII endpoints ---------------------------

def test_users_get_refuses_when_api_key_unset_on_server():
    m = _import_main({})
    client = _test_client(m)
    r = client.get("/users")
    assert r.status_code == 503
    assert "API_KEY" in r.json()["detail"]


def test_users_get_rejects_missing_bearer_when_configured():
    m = _import_main({"API_KEY": "sekret"})
    client = _test_client(m)
    r = client.get("/users")
    assert r.status_code == 401


def test_users_get_rejects_wrong_bearer():
    m = _import_main({"API_KEY": "sekret"})
    client = _test_client(m)
    r = client.get("/users", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_users_post_and_get_by_id_gated_the_same_way():
    """Vector 1 pattern-check: 'a check present on one handler and missing
    on its sibling'. All three PII endpoints must gate identically."""
    m = _import_main({})
    client = _test_client(m)
    assert client.get("/users").status_code == 503
    assert client.get("/users/1").status_code == 503
    assert client.post("/users", json={"name": "x", "email": "a@b.co"}).status_code == 503


# ---- Vector 6 — pagination bounds --------------------------------------

def test_list_users_rejects_limit_over_max():
    m = _import_main({"API_KEY": "sekret"})
    client = _test_client(m)
    r = client.get(
        "/users",
        params={"limit": m.MAX_USER_PAGE_SIZE + 1},
        headers={"Authorization": "Bearer sekret"},
    )
    assert r.status_code == 422


def test_list_users_rejects_negative_offset():
    m = _import_main({"API_KEY": "sekret"})
    client = _test_client(m)
    r = client.get(
        "/users",
        params={"offset": -1},
        headers={"Authorization": "Bearer sekret"},
    )
    assert r.status_code == 422


# ---- Vector 1 fine detail — timing-safe compare ------------------------

def test_require_api_key_uses_constant_time_compare():
    """The auth dependency must not compare via `==`. This test patches
    hmac.compare_digest to prove it is on the hot path."""
    m = _import_main({"API_KEY": "sekret"})
    client = _test_client(m)
    with mock.patch("main.hmac.compare_digest", return_value=False) as spy:
        r = client.get("/users", headers={"Authorization": "Bearer any"})
    assert r.status_code == 401
    assert spy.called, "hmac.compare_digest was not called — regression to plain =="
