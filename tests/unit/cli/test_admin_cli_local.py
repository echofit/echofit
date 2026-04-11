"""Subprocess tests for the real `echofit-admin` CLI in local mode.

Why subprocess (and not in-process imports)?
  These tests prove that the Click-based `echofit-admin` entry point
  defined in `mcp/pyproject.toml` actually parses, imports, and runs.
  An in-process import can't catch entry-point wiring regressions,
  missing dependencies, or shadowed command names.

Why pinned to `sys.executable.parent / "echofit-admin"` and not just
"echofit-admin" on $PATH?
  A developer may have `pipx install echofit-mcp` installed alongside
  the editable checkout. pipx puts its own `echofit-admin` shim on
  $PATH, and depending on shell init order it may resolve first. The
  tests would then silently exercise the pipx copy — possibly a
  stale release — and pass or fail based on code that isn't in this
  working tree. Pinning to the venv's bin dir guarantees the command
  is the one installed from `pip install -e mcp/` and therefore
  points at the code under test. If that binary isn't present
  (fresh clone, forgot `pip install -e mcp/`), the tests skip with
  a clear message instead of silently running the wrong thing.

Why isolated HOME and XDG dirs in the test env?
  `echofit-admin connect local` writes `setup.json` under
  `~/.config/echofit/` (resolved via XDG_CONFIG_HOME → HOME fallback).
  Without isolation the tests would pollute the developer's real
  config dir and could also pick up prior state from earlier runs,
  making test outcomes non-deterministic. `_env()` redirects every
  writable path that any code in the stack might touch.

Local mode means the admin CLI talks directly to the filesystem user
store — no HTTP server, no tokens (tokens are remote-only). This
covers the half of user management that the HTTP transport test
doesn't: the local filesystem path.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ECHOFIT_ADMIN = str(Path(sys.executable).parent / "echofit-admin")


def _env(tmp_path: Path) -> dict:
    """Isolated environment: all writable paths redirected to tmp_path."""
    env = os.environ.copy()
    env["APP_USERS_PATH"] = str(tmp_path / "users")
    env["ECHOFIT_DATA"] = str(tmp_path / "data")
    env["ECHOFIT_CONFIG"] = str(tmp_path / "config")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg_config")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg_data")
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir(exist_ok=True)
    return env


def _run(args: list, env: dict, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [ECHOFIT_ADMIN, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"echofit-admin {' '.join(args)} failed "
            f"(exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


@pytest.fixture(autouse=True)
def _require_admin_binary():
    if not Path(ECHOFIT_ADMIN).exists():
        pytest.skip(f"echofit-admin not installed at {ECHOFIT_ADMIN}")


def test_connect_local_then_add_list_and_revoke(tmp_path):
    """Full local user management flow: connect, add two users, list, revoke one."""
    env = _env(tmp_path)
    users_dir = tmp_path / "users"

    connect = _run(["connect", "local"], env)
    assert "local" in connect.stdout.lower()

    add_alice = _run(["users", "add", "alice@example.com"], env)
    assert "Added: alice@example.com" in add_alice.stdout

    add_bob = _run(["users", "add", "bob@example.com"], env)
    assert "Added: bob@example.com" in add_bob.stdout

    assert (users_dir / "alice~example.com" / "user.json").exists()
    assert (users_dir / "bob~example.com" / "user.json").exists()

    listed = _run(["users", "list"], env)
    assert "alice@example.com" in listed.stdout
    assert "bob@example.com" in listed.stdout

    health = _run(["health"], env)
    assert "local" in health.stdout.lower()

    revoke = _run(["users", "revoke", "alice@example.com"], env)
    assert "Revoked: alice@example.com" in revoke.stdout

    # Revoke should remove the user completely: auth record gone, and
    # the user should not appear in `users list`. This is what a user
    # of echofit-admin reasonably expects.
    #
    # KNOWN UPSTREAM BUG — echomodel/mcp-app#10:
    #   FileSystemUserDataStore.delete(user, "user") only unlinks
    #   user.json; the empty user directory is left behind, and
    #   list_users() walks directories, so revoked users still appear
    #   in `users list`. This assertion is expected to FAIL until
    #   mcp-app#10 is fixed and the dependency is bumped. Don't
    #   accommodate the bug in the test — fix mcp-app.
    assert not (users_dir / "alice~example.com" / "user.json").exists()

    after = _run(["users", "list"], env)
    assert "bob@example.com" in after.stdout
    assert "alice@example.com" not in after.stdout


def test_tokens_create_rejected_in_local_mode(tmp_path):
    """Tokens are a remote-only concept; local mode should decline."""
    env = _env(tmp_path)
    _run(["connect", "local"], env)
    _run(["users", "add", "alice@example.com"], env)

    result = _run(["tokens", "create", "alice@example.com"], env, check=False)
    assert "remote" in (result.stdout + result.stderr).lower()
