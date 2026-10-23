"""Smoke tests for the `echofit-mcp serve` HTTP entry point and the
admin CLI remote flow against a real running server.

Lives in `tests/integration/` because these bind a real TCP port
and spawn long-running processes. Excluded from default unit runs
by `pytest.ini`'s `testpaths`. Run with
`python -m pytest tests/integration/`.

What these prove:
  - `echofit-mcp serve` boots uvicorn with `AUTH_ISSUER` and
    `ADMIN_EMAILS` set, mounts the public routes, publishes the
    protected-resource metadata document, and answers an
    unauthenticated MCP request with the 401 challenge an MCP client
    follows to sign in.
  - `echofit-admin connect <url>` + `health` + `probe` work against a
    real server over real HTTP, exercising the remote admin client and
    per-app config persistence in `setup.json`.

No token is ever presented here: the server fetches the issuer's keys
lazily on the first bearer token, so a placeholder issuer is enough
to prove the front door. Token validation itself is covered in-process
by the framework suite (`tests/framework/`) against a test issuer.

Pinned to `sys.executable.parent / "<cmd>"` for both binaries — see
`tests/unit/cli/test_admin_cli_local.py` docstring for the pipx
interference rationale.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


ECHOFIT_MCP = str(Path(sys.executable).parent / "echofit-mcp")
ECHOFIT_ADMIN = str(Path(sys.executable).parent / "echofit-admin")
ISSUER = "https://issuer.example.test/"
OPERATOR = "operator@example.com"


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
    env = _isolated_env(tmp_path, {"AUTH_ISSUER": ISSUER, "ADMIN_EMAILS": OPERATOR})

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


def test_serve_publishes_discovery_and_challenges_anonymous_calls(running_server):
    """The OAuth front door: public metadata names the issuer and this
    server's own URL; an anonymous MCP request gets a 401 that points at
    that metadata."""
    base_url, _env = running_server

    metadata = httpx.get(f"{base_url}/.well-known/oauth-protected-resource", timeout=5.0)
    assert metadata.status_code == 200, metadata.text
    doc = metadata.json()
    assert doc["authorization_servers"] == [ISSUER]
    assert doc["resource"] == f"{base_url}/"

    resp = httpx.post(
        f"{base_url}/",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={"Accept": "application/json, text/event-stream"},
        timeout=5.0,
    )
    assert resp.status_code == 401, f"{resp.status_code} {resp.text}"
    challenge = resp.headers.get("www-authenticate", "")
    assert challenge.startswith("Bearer")
    assert "resource_metadata=" in challenge


def test_echofit_admin_remote_connect_health_and_probe(running_server, tmp_path):
    """Remote admin CLI flow against a live server, no credential involved.

    echofit-admin connect <url> → stores setup.json
    echofit-admin health → GET /health
    echofit-admin probe --json → health + discovery + 401 challenge
    """
    base_url, _server_env = running_server

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

    connect = run(["connect", base_url])
    assert base_url in connect.stdout

    health = run(["health"])
    assert "200" in health.stdout

    probe = json.loads(run(["probe", "--json"]).stdout)
    assert probe["oauth"]["status"] == "ok", probe
    assert probe["oauth"]["issuer"] == ISSUER
    assert probe["oauth"]["resource"] == f"{base_url}/"
