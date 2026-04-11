"""Full-stack stdio transport test against the real installed CLI.

Spawns `echofit-mcp stdio --user <email>` as a subprocess, drives
the MCP JSON-RPC protocol over its stdin/stdout pipes, and verifies
that per-user data lands in segregated directories on disk.

This is the stdio counterpart to `test_http_transport.py` — together
they cover both transports mcp-app supports.

Why subprocess (not in-process)?
  This test exists specifically to exercise the real Click entry
  point from `mcp/pyproject.toml`, the `mcp_cli` factory from
  mcp-app, and `run_stdio()` — all of which only run when the
  installed console script is invoked. An in-process test wouldn't
  catch a broken entry point, a missing import in the installed
  package, or a Click arg-parsing regression.

Why pinned to `sys.executable.parent / "echofit-mcp"`?
  See `tests/unit/cli/test_admin_cli_local.py` for the full
  rationale. Short version: a developer may have pipx-installed
  `echofit-mcp` alongside the editable checkout, and PATH may
  resolve the pipx copy first. Pinning to the venv's bin dir
  guarantees the command is the one installed by
  `pip install -e mcp/` and therefore points at the working-tree
  code under test.

TDD note:
  These tests assert *correct* behavior. If the stdio entry point,
  yaml discovery, or per-user data segregation is broken, the test
  will fail — that is the signal to fix the code, not the test.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ECHOFIT_MCP = str(Path(sys.executable).parent / "echofit-mcp")
REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["APP_USERS_PATH"] = str(tmp_path / "users")
    env["ECHOFIT_DATA"] = str(tmp_path / "data")
    env["ECHOFIT_CONFIG"] = str(tmp_path / "config")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg_config")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg_data")
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir(exist_ok=True)
    return env


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


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _recv_until_id(proc: subprocess.Popen, target_id: int, timeout_lines: int = 50) -> dict:
    """Read JSON-RPC replies from stdout until one matches target_id."""
    for _ in range(timeout_lines):
        line = proc.stdout.readline()
        if not line:
            raise AssertionError(
                f"server closed stdout before response id={target_id}; "
                f"stderr: {proc.stderr.read() if proc.stderr else ''}"
            )
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == target_id:
            return msg
    raise AssertionError(f"no response with id={target_id} after {timeout_lines} lines")


def _log_meal_via_stdio(
    env: dict, user: str, food_name: str, cwd: Path
) -> dict:
    """Spawn echofit-mcp stdio and drive a single log_meal tool call."""
    proc = subprocess.Popen(
        [ECHOFIT_MCP, "stdio", "--user", user],
        env=env,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        _send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest-stdio", "version": "1.0"},
            },
        })
        init_reply = _recv_until_id(proc, 1)
        assert "result" in init_reply, f"initialize failed: {init_reply}"

        _send(proc, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })

        _send(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "log_meal",
                "arguments": {"food_entries": [_food_entry(food_name)]},
            },
        })
        call_reply = _recv_until_id(proc, 2)
        assert "result" in call_reply, f"tool call failed: {call_reply}"
        return call_reply
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


@pytest.fixture(autouse=True)
def _require_mcp_binary():
    if not Path(ECHOFIT_MCP).exists():
        pytest.skip(f"echofit-mcp not installed at {ECHOFIT_MCP}")


def test_stdio_segregates_data_per_user_from_repo_root(tmp_path):
    """Two stdio sessions for two users → two isolated data dirs on disk."""
    env = _env(tmp_path)
    users_dir = tmp_path / "users"

    _log_meal_via_stdio(env, "alice@example.com", "Alice Apple", cwd=REPO_ROOT)
    _log_meal_via_stdio(env, "bob@example.com", "Bob Banana", cwd=REPO_ROOT)

    alice_daily = users_dir / "alice~example.com" / "daily"
    bob_daily = users_dir / "bob~example.com" / "daily"
    assert alice_daily.exists(), f"alice daily missing; users_dir={list(users_dir.iterdir()) if users_dir.exists() else 'MISSING'}"
    assert bob_daily.exists(), f"bob daily missing; users_dir={list(users_dir.iterdir()) if users_dir.exists() else 'MISSING'}"

    alice_files = list(alice_daily.iterdir())
    bob_files = list(bob_daily.iterdir())
    assert len(alice_files) == 1
    assert len(bob_files) == 1

    alice_log = json.loads(alice_files[0].read_text())
    bob_log = json.loads(bob_files[0].read_text())
    alice_names = [e["food_name"] for e in alice_log]
    bob_names = [e["food_name"] for e in bob_log]

    assert alice_names == ["Alice Apple"]
    assert bob_names == ["Bob Banana"]


def test_stdio_get_food_log_settings_no_args(tmp_path):
    """A zero-argument tool round-trips correctly over stdio.

    Covers a different shape from log_meal: no input schema, just a
    plain dict return. Proves FastMCP tool discovery handles both
    argument-bearing and argument-free async functions from the
    tools module.
    """
    env = _env(tmp_path)

    proc = subprocess.Popen(
        [ECHOFIT_MCP, "stdio", "--user", "alice@example.com"],
        env=env,
        cwd=str(REPO_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest-stdio", "version": "1.0"},
            },
        })
        assert "result" in _recv_until_id(proc, 1)
        _send(proc, {
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        })
        _send(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "get_food_log_settings", "arguments": {}},
        })
        reply = _recv_until_id(proc, 2)
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

    assert "result" in reply, f"tool call failed: {reply}"
    payload = reply["result"]
    text = json.dumps(payload)
    assert "timezone" in text
    assert "hours_offset" in text


def test_stdio_works_from_an_empty_cwd(tmp_path):
    """End users pipx-install echofit-mcp and run it from anywhere.

    A `pipx install echofit-mcp` user will invoke `echofit-mcp stdio`
    from their home directory — not from the repo. The app MUST
    locate its own mcp-app.yaml regardless of cwd (bundled inside
    the installed package via setuptools package-data).

    If this test fails, the fix is to:
      1. Move or copy `mcp-app.yaml` to `sdk/echofit/mcp-app.yaml`
      2. Add it to `sdk/pyproject.toml` under
         `[tool.setuptools.package-data]`
      3. Ensure `_find_app_config("echofit")` in mcp-app discovers it

    Do NOT "fix" this test by setting cwd=REPO_ROOT. That would hide
    a real deployment bug.
    """
    env = _env(tmp_path)
    users_dir = tmp_path / "users"
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()

    _log_meal_via_stdio(env, "alice@example.com", "Alice Apple", cwd=empty_cwd)

    alice_daily = users_dir / "alice~example.com" / "daily"
    assert alice_daily.exists()
    alice_files = list(alice_daily.iterdir())
    assert len(alice_files) == 1
    alice_log = json.loads(alice_files[0].read_text())
    assert alice_log[0]["food_name"] == "Alice Apple"
