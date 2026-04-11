"""Full-stack in-process HTTP transport test.

Exercises the real ASGI stack against the working-tree code:
build_app() → JWTMiddleware → FastMCP tool dispatch → DietSDK →
filesystem store. Per-user data segregation is verified on disk.

No subprocess, no port, no uvicorn. httpx ASGI transport drives
Starlette directly. mcp.session_manager.run() is entered manually
because httpx ASGI transport does not fire Starlette lifespan events.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt as pyjwt
import pytest


SIGNING_KEY = "test-signing-key-not-a-real-secret-please-ignore-xx"


def _food_entry(name: str) -> dict:
    return {
        "food_name": name,
        "consumed": {
            "nutrition": {
                "calories": 100, "protein": 5, "carbs": 10, "fat": 3,
            },
        },
        "confidence_score": 8,
    }


def _admin_jwt() -> str:
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {
            "sub": "admin",
            "scope": "admin",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SIGNING_KEY,
        algorithm="HS256",
    )


def _parse_mcp_response(resp: httpx.Response) -> dict:
    """Parse either application/json or text/event-stream JSON-RPC reply."""
    ctype = resp.headers.get("content-type", "")
    if "application/json" in ctype:
        return resp.json()
    # SSE framing: find the data: line with the JSON payload
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"No JSON-RPC payload in response: {resp.text!r}")


async def _mcp_call(client: httpx.AsyncClient, token: str, payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    resp = await client.post("/", json=payload, headers=headers)
    assert resp.status_code == 200, f"MCP call failed: {resp.status_code} {resp.text}"
    return _parse_mcp_response(resp)


async def _log_meal_as(client: httpx.AsyncClient, token: str, food_name: str) -> dict:
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "log_meal",
            "arguments": {"food_entries": [_food_entry(food_name)]},
        },
    }
    return await _mcp_call(client, token, call)


async def _register_user(client: httpx.AsyncClient, admin_token: str, email: str) -> str:
    resp = await client.post(
        "/admin/users",
        json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, f"register failed: {resp.status_code} {resp.text}"
    return resp.json()["token"]


async def _drive(data_dir: Path) -> None:
    # Import here so env vars are patched before module-level DietSDK() runs.
    from mcp_app.bootstrap import build_app
    from echofit import APP_NAME
    from echofit_mcp.diet import tools as diet_tools

    app, mcp, store, config = build_app(name=APP_NAME, tools_module=diet_tools)

    admin_token = _admin_jwt()

    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            alice_token = await _register_user(client, admin_token, "alice@example.com")
            bob_token = await _register_user(client, admin_token, "bob@example.com")

            alice_resp = await _log_meal_as(client, alice_token, "Alice Apple")
            bob_resp = await _log_meal_as(client, bob_token, "Bob Banana")

    assert "result" in alice_resp, f"alice result missing: {alice_resp}"
    assert "result" in bob_resp, f"bob result missing: {bob_resp}"

    alice_daily = data_dir / "alice~example.com" / "daily"
    bob_daily = data_dir / "bob~example.com" / "daily"

    assert alice_daily.exists(), f"alice dir missing: {list(data_dir.iterdir())}"
    assert bob_daily.exists(), f"bob dir missing: {list(data_dir.iterdir())}"

    alice_files = list(alice_daily.iterdir())
    bob_files = list(bob_daily.iterdir())
    assert len(alice_files) == 1
    assert len(bob_files) == 1

    alice_log = json.loads(alice_files[0].read_text())
    bob_log = json.loads(bob_files[0].read_text())

    alice_names = [e["food_name"] for e in alice_log]
    bob_names = [e["food_name"] for e in bob_log]
    assert "Alice Apple" in alice_names
    assert "Bob Banana" in bob_names
    assert "Bob Banana" not in alice_names
    assert "Alice Apple" not in bob_names


def test_multi_user_http_end_to_end_segregation(tmp_path):
    """End-to-end: admin register → per-user JWT → MCP tool call → segregated files."""
    data_dir = tmp_path / "users"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with patch.dict(
        os.environ,
        {
            "APP_USERS_PATH": str(data_dir),
            "ECHOFIT_CONFIG": str(config_dir),
            "SIGNING_KEY": SIGNING_KEY,
        },
    ):
        asyncio.run(_drive(data_dir))


def _user_jwt(email: str, *, exp_delta: timedelta = timedelta(minutes=5)) -> str:
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {"sub": email, "iat": now, "exp": now + exp_delta},
        SIGNING_KEY,
        algorithm="HS256",
    )


def _tmp_env(tmp_path: Path) -> dict:
    data_dir = tmp_path / "users"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return {
        "APP_USERS_PATH": str(data_dir),
        "ECHOFIT_CONFIG": str(config_dir),
        "SIGNING_KEY": SIGNING_KEY,
    }


def _build():
    from mcp_app.bootstrap import build_app
    from echofit import APP_NAME
    from echofit_mcp.diet import tools as diet_tools

    return build_app(name=APP_NAME, tools_module=diet_tools)


def test_http_rejects_request_without_token(tmp_path):
    """JWTMiddleware rejects requests with no Authorization header."""
    async def _run():
        app, mcp, store, config = _build()
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Accept": "application/json, text/event-stream"},
                )
                assert resp.status_code == 401

    with patch.dict(os.environ, _tmp_env(tmp_path)):
        asyncio.run(_run())


def test_http_rejects_tool_call_for_unregistered_user(tmp_path):
    """Valid signature, unknown sub → verifier returns None → 403."""
    async def _run():
        app, mcp, store, config = _build()
        ghost_token = _user_jwt("ghost@example.com")
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={
                        "Authorization": f"Bearer {ghost_token}",
                        "Accept": "application/json, text/event-stream",
                    },
                )
                assert resp.status_code == 403

    with patch.dict(os.environ, _tmp_env(tmp_path)):
        asyncio.run(_run())


def test_http_rejects_tool_call_for_expired_token(tmp_path):
    """Expired user JWT is rejected by the middleware."""
    async def _run():
        app, mcp, store, config = _build()
        admin = _admin_jwt()
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                reg = await client.post(
                    "/admin/users",
                    json={"email": "alice@example.com"},
                    headers={"Authorization": f"Bearer {admin}"},
                )
                assert reg.status_code == 200
                expired = _user_jwt(
                    "alice@example.com", exp_delta=timedelta(seconds=-60)
                )
                resp = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={
                        "Authorization": f"Bearer {expired}",
                        "Accept": "application/json, text/event-stream",
                    },
                )
                assert resp.status_code == 403

    with patch.dict(os.environ, _tmp_env(tmp_path)):
        asyncio.run(_run())


def test_admin_endpoint_rejects_non_admin_scope(tmp_path):
    """A valid user-scope JWT must not grant access to /admin/users."""
    async def _run():
        app, mcp, store, config = _build()
        admin = _admin_jwt()
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                reg = await client.post(
                    "/admin/users",
                    json={"email": "alice@example.com"},
                    headers={"Authorization": f"Bearer {admin}"},
                )
                assert reg.status_code == 200
                alice_token = reg.json()["token"]

                resp = await client.post(
                    "/admin/users",
                    json={"email": "mallory@example.com"},
                    headers={"Authorization": f"Bearer {alice_token}"},
                )
                assert resp.status_code == 403

    with patch.dict(os.environ, _tmp_env(tmp_path)):
        asyncio.run(_run())
