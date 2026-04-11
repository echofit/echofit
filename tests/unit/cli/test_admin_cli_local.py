"""Local-revoke proving-ground test for the admin CLI.

Everything else that used to live in this file (connect, add, list,
health, tokens-rejected) now belongs to `mcp_app.testing.iam.test_admin_local`,
which the framework runs against echofit's `App` via
`tests/framework/test_framework.py`. This file is what's left after
that consolidation.

Why this one test still lives in echofit:
  `users revoke` is not yet verified by the mcp-app framework's
  IAM tests. Echofit's revoke test is the only current signal
  exercising `FileSystemUserDataStore.delete()`, and it's the test
  that surfaces echomodel/mcp-app#10 (empty-dir-after-revoke bug).
  Deleting it now would remove tracking of that upstream bug.
  When mcp-app adds a revoke check and #10 is fixed, this file
  should be deleted entirely.

Why the subprocess + sys.executable.parent pinning pattern is still
used here is documented in `CONTRIBUTING.md` and was originally
written for this file before being generalized upstream — see
`mcp_app.testing.fixtures` for the framework-level equivalent.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


ECHOFIT_ADMIN = str(Path(sys.executable).parent / "echofit-admin")


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


def _run(args: list, env: dict) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [ECHOFIT_ADMIN, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"echofit-admin {' '.join(args)} failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


@pytest.fixture(autouse=True)
def _require_admin_binary():
    if not Path(ECHOFIT_ADMIN).exists():
        pytest.skip(f"echofit-admin not installed at {ECHOFIT_ADMIN}")


def test_revoke_removes_user_record_and_drops_from_list(tmp_path):
    """Revoke in local mode deletes the auth record and the user
    disappears from `users list`.

    KNOWN UPSTREAM BUG — echomodel/mcp-app#10:
      FileSystemUserDataStore.delete(user, "user") only unlinks
      user.json; the empty user directory is left behind, and
      list_users() walks directories, so revoked users still appear
      in `users list`. This assertion is expected to FAIL until
      mcp-app#10 is fixed and the dependency is bumped. Don't
      accommodate the bug in the test — fix mcp-app.
    """
    env = _env(tmp_path)
    users_dir = tmp_path / "users"

    _run(["connect", "local"], env)
    _run(["users", "add", "alice@example.com"], env)
    _run(["users", "add", "bob@example.com"], env)

    assert (users_dir / "alice~example.com" / "user.json").exists()

    revoke = _run(["users", "revoke", "alice@example.com"], env)
    assert "Revoked: alice@example.com" in revoke.stdout

    # Auth record gone — this part already passes.
    assert not (users_dir / "alice~example.com" / "user.json").exists()

    # User disappears from `users list` — blocked on mcp-app#10.
    after = _run(["users", "list"], env)
    assert "bob@example.com" in after.stdout
    assert "alice@example.com" not in after.stdout
