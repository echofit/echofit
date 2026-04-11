"""Smoke tests for the `echofit-mcp serve` HTTP entry point and the
admin CLI remote flow against a real running server.

Lives in `tests/integration/` because these bind a real TCP port
and spawn long-running processes. Excluded from default unit runs
by `pytest.ini`'s `testpaths = tests/unit`. Run with
`python -m pytest tests/integration/`.

What these prove:
  - `echofit-mcp serve` boots uvicorn, loads the ASGI stack, mounts
    routes, and accepts one successful authenticated request.
  - `echofit-admin connect <url>` + `users add` + `tokens create`
    work against a real server over real HTTP — exercising the
    RemoteAuthAdapter end-to-end, including per-user config
    persistence in `_save_setup`.

Functional HTTP coverage (per-user segregation, auth rejection
paths, etc.) lives in `tests/unit/mcp/test_http_transport.py` via
in-process httpx ASGI transport. These tests are intentionally
minimal smoke — just enough to prove the subprocess-level wiring.

Pinned to `sys.executable.parent / "<cmd>"` for both binaries — see
`tests/unit/cli/test_admin_cli_local.py` docstring for the pipx
interference rationale.
"""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import jwt as pyjwt
import pytest


ECHOFIT_MCP = str(Path(sys.executable).parent / "echofit-mcp")
ECHOFIT_ADMIN = str(Path(sys.executable).parent / "echofit-admin")
SIGNING_KEY = "test-signing-key-not-a-real-secret-please-ignore-xx"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_ready(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=1.0)
            if resp.status_code < 500:
                return
        except Exception as e:
            last_error = e
        time.sleep(0.1)
    raise AssertionError(f"server did not become ready at {url}: {last_error}")


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


def _isolated_env(tmp_path: Path, extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env["APP_USERS_PATH"] = str(tmp_path / "users")
    env["ECHOFIT_DATA"] = str(tmp_path / "data")
    env["ECHOFIT_CONFIG"] = str(tmp_path / "config")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg_config")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg_data")
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir(exist_ok=True)
    if extra:
        env.update(extra)
    return env


@pytest.fixture(autouse=True)
def _require_binaries():
    missing = [p for p in (ECHOFIT_MCP, ECHOFIT_ADMIN) if not Path(p).exists()]
    if missing:
        pytest.skip(f"binaries not installed: {missing}")


@pytest.fixture
def running_server(tmp_path):
    """Spawn echofit-mcp serve on a free port. Yields (base_url, env)."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = _isolated_env(tmp_path, {"SIGNING_KEY": SIGNING_KEY})

    proc = subprocess.Popen(
        [ECHOFIT_MCP, "serve", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_ready(f"{base_url}/health")
        yield base_url, env
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def test_serve_boots_and_accepts_one_admin_request(running_server):
    """Minimal smoke: server up, one admin register succeeds."""
    base_url, _env = running_server
    resp = httpx.post(
        f"{base_url}/admin/users",
        json={"email": "smoke@example.com"},
        headers={"Authorization": f"Bearer {_admin_jwt()}"},
        timeout=5.0,
    )
    assert resp.status_code == 200, f"admin register failed: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["email"] == "smoke@example.com"
    assert "token" in body


def test_echofit_admin_remote_connect_add_and_token(running_server, tmp_path):
    """Full remote admin CLI flow against a live server.

    echofit-admin connect <url> → stores setup.json
    echofit-admin users add alice → POSTs /admin/users, prints token
    echofit-admin users list → lists via GET /admin/users
    """
    base_url, server_env = running_server

    # Separate HOME for the admin CLI — do NOT share the server's
    # XDG state, since connect writes setup.json and we want to
    # verify the CLI client works independently of the server process.
    cli_home = tmp_path / "cli_home"
    cli_home.mkdir()
    cli_env = os.environ.copy()
    cli_env["HOME"] = str(cli_home)
    cli_env["XDG_CONFIG_HOME"] = str(tmp_path / "cli_xdg_config")
    cli_env["XDG_DATA_HOME"] = str(tmp_path / "cli_xdg_data")
    cli_env["ECHOFIT_CONFIG"] = str(tmp_path / "cli_config")

    def run(args):
        result = subprocess.run(
            [ECHOFIT_ADMIN, *args],
            env=cli_env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"echofit-admin {' '.join(args)} failed ({result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        return result

    connect = run(["connect", base_url, "--signing-key", SIGNING_KEY])
    assert base_url in connect.stdout

    add = run(["users", "add", "alice@example.com"])
    assert "Added: alice@example.com" in add.stdout
    assert "Token:" in add.stdout

    listed = run(["users", "list"])
    assert "alice@example.com" in listed.stdout

    tokens = run(["tokens", "create", "alice@example.com"])
    assert "alice@example.com" in tokens.stdout
    # A JWT has three base64url segments joined by dots.
    assert tokens.stdout.count(".") >= 2

    # NOTE: `echofit-admin health` is intentionally NOT asserted here.
    # Upstream mcp-app passes /health through JWTMiddleware but does
    # not register a /health route, so the server currently returns
    # 404. The admin CLI still reports "healthy (404)" because it
    # considers any non-5xx response reachable. Worth a separate
    # upstream bug; not this test's concern.
