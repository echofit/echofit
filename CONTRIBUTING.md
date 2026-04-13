# Contributing to EchoFit

## Architecture

### Three distribution packages, one repo

| PyPI package | Import name | Purpose | Depends on |
|-------------|-------------|---------|------------|
| `echofit-sdk` | `echofit` | All business logic | — |
| `echofit-mcp` | `echofit_mcp` | MCP server (AI tool interface) | `echofit-sdk` |
| `echofit` | `echofit_cli` | CLI | `echofit-sdk` |

**Why three:** A Claude plugin user shouldn't install Click. A developer using the SDK shouldn't install the MCP framework. A CLI user shouldn't install MCP either.

### SDK-first

All business logic lives in `sdk/echofit/`. MCP tools and CLI commands are thin wrappers that call SDK methods and return the result.

```
sdk/echofit/                   # echofit-sdk package
  __init__.py                  # APP_NAME constant
  config.py                    # Timezone, paths, XDG resolution, app config
  context.py                   # User identity (re-exports current_user from mcp-app)
  app.yaml                     # Timezone and day boundary config
  diet/                        # Diet tracking module
    core.py                    # DietSDK — logging, catalog, entry management
    rounding.py                # FDA nutrition rounding
  workout/                     # Workout tracking module
    core.py                    # WorkoutSDK — exercise catalog, workout logging

mcp/echofit_mcp/               # echofit-mcp package
  __init__.py                  # Constructs the App composition root (single export: `app`)
  tools.py                     # Aggregator — re-exports tools from all modules
  diet/
    tools.py                   # Diet MCP tools — thin async wrappers
  workout/
    tools.py                   # Workout MCP tools — thin async wrappers

cli/echofit_cli/               # echofit (CLI) package
  main.py                      # Click CLI commands
  cloud.py                     # Cloud deployment utilities
```

If you're writing logic in an MCP tool or CLI command, stop and move it to the SDK.

### Modules

EchoFit is organized into feature modules within the SDK. Each module has a parallel structure in the MCP and CLI layers:

- `echofit.diet` — diet/nutrition tracking (SDK)
- `echofit_mcp.diet` — MCP tools for diet (thin wrappers)
- `echofit.workout` — exercise logging (SDK)
- `echofit_mcp.workout` — MCP tools for workout (thin wrappers)

Modules do not import each other. They share `echofit.config` and `echofit.context` for user identity and data path resolution. Adding a module = add a subdir in `sdk/echofit/`, add a corresponding subdir in `mcp/echofit_mcp/`, optionally add CLI commands.

Diet and workout share a **daily journal of entries** pattern — one log file per day, entries appended, same CRUD operations (log, revise, move between dates, filter). Where possible, shared infrastructure (date handling, entry ID generation, daily log file management) should be reused across these modules rather than duplicated. Health/vitals (e.g., blood pressure tracking) will have different data structures and access patterns — reads are more analytical (trends over time) and writes may not follow the daily-entries model. There is a need to be thoughtful about allowing for reuse and code consolidation at higher or lower levels in the user data model depending upon need. Three modules might share a common part of the echofit (or broader echomodel) user data storage framework, while only two of those three share a more specific element of a user data framework — e.g., logged entries in a journal that's typically viewed and managed in daily terms.

All modules ship together in `echofit-sdk` — there are no per-module packages (no `echofit-diet`, `echofit-workout`). Module visibility is controlled at runtime via server config and JWT claims, not at install time. See the README for details on module configuration.

### SDK returns dicts

SDK methods return JSON-serializable dicts. Both MCP tools and CLI commands use the same return values. MCP tools return them directly. CLI formats for humans.

### User identity and data path resolution

User identity flows via `current_user` ContextVar (re-exported from `mcp_app.context`), which holds a `UserRecord` object with `.email` and `.profile` fields.

**Two modes:**

| Mode | Transport | `current_user.email` | Data path |
|------|-----------|----------------------|-----------|
| **Single-user (stdio)** | stdio | `"local"` (set via `--user local`) | `~/.local/share/echofit/` |
| **Multi-user (HTTP)** | HTTP/SSE | Set from JWT `sub` claim by mcp-app middleware | `~/.local/share/echofit/{user}` (or `APP_USERS_PATH/{user}` in cloud) |

In stdio mode, passing `--user local` (or any placeholder email) to `echofit-mcp stdio` sets `current_user` to a `UserRecord(email="local")`, and data goes directly to the base data directory — no user subdirectory. In HTTP mode, mcp-app's user-identity middleware validates the JWT, loads the full user record from the store in one read, and sets `current_user`, which causes `get_app_data_dir()` to return a user-scoped subdirectory.

The SDK reads `current_user.get().email` — it never imports MCP or transport-layer code. This means all modules (diet, workout, etc.) get user-scoped data for free without knowing how the user was identified.

## Adding Features

1. **SDK first** — implement in `sdk/echofit/<module>/` (e.g., `sdk/echofit/workout/core.py`)
2. **MCP tools** — add thin async wrappers in `mcp/echofit_mcp/<module>/tools.py`
3. **CLI commands** (optional) — add a Click command group in `cli/echofit_cli/`
4. **Tests** — add sociable unit tests for the SDK method(s) in `tests/unit/sdk/`. If the tool references a new SDK method, the framework's `mcp_app.testing.tools.test_sdk_coverage_audit` will fail until a test references that method by name. Framework-owned concerns (auth, admin CLI, app wiring, HTTP health) are verified automatically by `tests/framework/` — do not duplicate them.

## Testing

### Philosophy: sociable unit tests

Tests verify complete features or SDK transactions end-to-end. No mocks unless needed for network I/O. Isolate via temp dirs and env vars — the same env vars the solution reads in production.

### Test directory structure

```
tests/
  framework/                   # Free tests against this echofit app sourced from the mcp-app
                               # framework, verifying mission-critical operational functionality
                               # (user auth, user admin, JWT enforcement) — 26 tests, DEFAULT
    conftest.py                # Hands the framework your App object
    test_framework.py          # Imports the subsystem test modules mcp-app ships
  unit/                        # Echofit-specific tests (DEFAULT)
    sdk/                       # Business logic — the bulk of echofit's tests
      test_diet_core.py        # logging, timezone, day boundary, move entries
      test_catalog.py          # catalog CRUD + revise_log_entry
      test_user_data_paths.py  # XDG path resolution with current_user
    mcp/                       # In-process MCP tool delegation tests
      test_diet_tools.py       # thin-wrapper delegation + SDK-level data segregation
      test_stdio_transport.py  # subprocess `echofit-mcp stdio` JSON-RPC over pipes
    cli/                       # Echofit CLI tests
      test_cloud_config.py     # echofit_cli gcloud config helpers
      test_admin_cli_local.py  # proving-ground revoke test (tracks mcp-app#10)
  integration/                 # Requires real subprocess + port (NEVER default)
    test_echofit_mcp_serve.py  # subprocess `echofit-mcp serve` boot + remote admin CLI flow
  cloud/                       # Requires cloud deployment (NEVER default)
    test_in_cloud.py
    test_admin_cloud_security.py
```

### `tests/framework/` — free tests from mcp-app that verify mission-critical functionality

Echofit's `tests/framework/` directory contains **free tests against this echofit app sourced from the mcp-app framework that verify mission-critical operational functionality** — the plumbing mcp-app itself owns and echofit depends on: user auth, user admin, JWT enforcement, admin CLI flows, app wiring, HTTP health, and SDK test-coverage discipline. These tests did not have to be written. They were imported. Twenty-six of them run on every `pytest` invocation, and if any one of them fails, something mission-critical in this solution is broken.

**Why this exists at all:** the mcp-app framework provides user management, auth middleware, admin endpoints, and a CLI factory that every mcp-app solution inherits. Those features are mission-critical — if `POST /admin/users` silently stops registering users, or if an expired JWT stops returning 403, or if `echofit-admin connect local` stops writing `setup.json` correctly, echofit is broken in production even though no line of echofit code moved. Echofit alone can't detect those regressions by reading its own business logic tests. The framework has to verify its own features are actually wired up correctly in each solution that uses it. `tests/framework/` is how that verification happens for echofit specifically.

**What each subsystem package verifies in plain terms:**

- **`mcp_app.testing.iam`** — **identity and access management**. Three modules:
  - `test_auth_enforcement` — your running HTTP server actually enforces auth. Missing token → 401. Unregistered user → 403. Expired token → 403. Non-admin scope on `/admin/users` → 403. Profile data round-trips through admin registration. **This is the group that catches an auth regression before it reaches production.**
  - `test_admin_local` — your installed `echofit-admin` binary actually talks to the local filesystem user store via real subprocess. `connect local`, `users add`, `users list`, `health`, `tokens create` (rejected in local mode) all behave correctly end-to-end.
  - `test_admin_errors` — misuse of `echofit-admin` fails loudly and informatively. `users add` without prior `connect` errors clearly. `connect <url>` without `--signing-key` errors. `health` without `connect` errors. If an error path stops erroring, users will quietly generate wrong state.
- **`mcp_app.testing.wiring`** — **app and entry-point wiring**. `App.mcp_cli` and `App.admin_cli` are real Click groups with the expected subcommands. Every public MCP tool has a docstring and a return-type annotation (required for the MCP protocol). App name is set. If any of this drifts, the server won't boot and the MCP client won't see valid tool schemas.
- **`mcp_app.testing.tools`** — **SDK test-coverage audit**. An AST-based auditor that walks every public async tool in `echofit_mcp.diet.tools`, finds every `sdk.<method>(...)` call site, and verifies each method name appears in at least one file under `tests/unit/sdk/`. If a new tool is added that calls a new SDK method without a corresponding unit test, this fails with a structured diagnostic listing the gap. Not fuzzy string matching: the tool-to-method mapping is built by AST walk; only the SDK-test presence check is a substring match, and SDK method names are distinct Python identifiers so collisions can't happen.
- **`mcp_app.testing.health`** — **HTTP liveness**. Verifies `/health` returns 200 OK so Cloud Run (and any other liveness-check-driven platform) will keep the instance in rotation.

**Do not rebuild any of this in `tests/unit/`.** If you catch yourself writing a test that duplicates one of these, delete it and trust the framework. If a framework test fails, read the assertion message and fix your implementation — never the imported test file.

**`tests/unit/sdk/`** — The bulk of all tests. Test SDK methods directly. Cover business logic, data persistence, date/timezone handling, catalog CRUD, entry management. These call SDK classes with `current_user` set manually via `UserRecord(email=...)` and `ECHOFIT_DATA`/`ECHOFIT_CONFIG` pointed at temp dirs.

**`tests/unit/mcp/`** — In-process MCP transport tests that cover things the framework tests don't. Today this includes `test_diet_tools.py` (thin-wrapper delegation + SDK-level per-user data segregation) and `test_stdio_transport.py` (subprocess stdio via JSON-RPC over pipes — mcp-app's framework tests cover HTTP but not stdio transport). If mcp-app later adds a stdio equivalent, delete the redundant bits.

**`tests/unit/cli/`** — Echofit-specific CLI tests. Today: `test_cloud_config.py` (echofit's own gcloud config helpers, not mcp-app's admin CLI) and `test_admin_cli_local.py` (proving-ground subprocess test for `users revoke` in local mode, which tracks echomodel/mcp-app#10 and which the framework doesn't yet cover — delete this file when mcp-app adds its own revoke verification).

### Adopting this pattern in a new mcp-app solution

If you're building a new mcp-app solution and want the same free mission-critical test coverage, the adoption is five steps and ~25 lines of code:

1. **Construct an `App` in your MCP package's `__init__.py`:**
   ```python
   from mcp_app import App
   import my_app
   from my_app_mcp.tools import tools as my_tools
   app = App(name="my-app", tools_module=my_tools, sdk_package=my_app)
   ```
2. **Register the `mcp_app.apps` entry point in your `pyproject.toml`:**
   ```toml
   [project.scripts]
   my-app-mcp = "my_app_mcp:app.mcp_cli"
   my-app-admin = "my_app_mcp:app.admin_cli"

   [project.entry-points."mcp_app.apps"]
   my-app = "my_app_mcp:app"
   ```
3. **Create `tests/framework/conftest.py`:**
   ```python
   import pytest
   from my_app_mcp import app as my_app

   @pytest.fixture(scope="session")
   def app():
       return my_app
   ```
4. **Create `tests/framework/test_framework.py`:**
   ```python
   from mcp_app.testing.iam.test_auth_enforcement import *       # noqa
   from mcp_app.testing.iam.test_admin_local import *            # noqa
   from mcp_app.testing.iam.test_admin_errors import *           # noqa
   from mcp_app.testing.wiring.test_app_wiring import *          # noqa
   from mcp_app.testing.tools.test_sdk_coverage_audit import *   # noqa
   from mcp_app.testing.health.test_health import *              # noqa
   ```
5. **Update `pytest.ini`:**
   ```ini
   [pytest]
   testpaths = tests/unit tests/framework
   asyncio_mode = strict
   ```
   Plus declare `pytest-asyncio` as a test dependency (the framework's HTTP auth-enforcement tests are async).

After that, every `pytest` run executes the full set of mission-critical framework tests against your app. See `tests/framework/conftest.py` and `tests/framework/test_framework.py` in this repo for the actual working example.

### Installing test dependencies

The framework tests require `pytest-asyncio` (the HTTP ones are async). Install the test extras:

```bash
pip install -e 'mcp/[test]'
```

Or install it directly:

```bash
pip install pytest pytest-asyncio httpx
```

### Testing user data isolation

The critical thing to test across layers: **data written through one transport for one user does not leak to another user or another transport mode.**

```python
# Example: prove multi-user data isolation
@pytest.fixture
def tmp_env(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with patch.dict(os.environ, {"ECHOFIT_DATA": str(data_dir)}):
        yield data_dir

def test_multi_user_data_isolation(tmp_env):
    """Two users' data lands in separate directories."""
    from mcp_app.models import UserRecord
    from echofit.context import current_user

    token = current_user.set(UserRecord(email="alice@example.com"))
    try:
        sdk = DietSDK()
        sdk.log_food([...])
        assert (tmp_env / "alice~example.com" / "daily").exists()
    finally:
        current_user.reset(token)

    token = current_user.set(UserRecord(email="bob@example.com"))
    try:
        sdk = DietSDK()
        sdk.log_food([...])
        assert (tmp_env / "bob~example.com" / "daily").exists()
    finally:
        current_user.reset(token)

    # Alice's data is not in Bob's directory
    alice_files = list((tmp_env / "alice~example.com" / "daily").iterdir())
    bob_files = list((tmp_env / "bob~example.com" / "daily").iterdir())
    assert len(alice_files) == 1
    assert len(bob_files) == 1
```

### Environment variable isolation

Every test must be isolated from real user data. Use `ECHOFIT_DATA` and `ECHOFIT_CONFIG` env var overrides pointed at `tmp_path`. Tests use the same env vars the solution reads in production.

### Test names

Describe scenario + outcome:
- Good: `test_logs_food_to_current_date_directory`
- Good: `test_multi_user_data_lands_in_separate_directories`
- Bad: `test_returns_true_when_file_exists`

### Testing entry points without pipx interference

Some tests shell out to the real installed CLIs (`echofit-admin`, `echofit-mcp`) to prove the `pyproject.toml` entry points, Click parsing, and module imports actually work. These tests **must not** rely on `$PATH` to find the binary.

The reason: a developer may have `pipx install echofit-mcp` installed alongside the editable checkout. pipx places its own shims on `$PATH`, and depending on shell init order, those shims can resolve before the venv's bin dir. A test that calls bare `echofit-mcp` would then silently exercise the pipx copy — possibly a stale release — and pass or fail based on code that isn't in this working tree. The test appears to be verifying your changes, but isn't.

**The rule:** subprocess-based CLI tests pin the command to the current interpreter's bin dir:

```python
import sys
from pathlib import Path

ECHOFIT_MCP = str(Path(sys.executable).parent / "echofit-mcp")
ECHOFIT_ADMIN = str(Path(sys.executable).parent / "echofit-admin")
```

Because pytest runs under the venv's Python, `sys.executable.parent` is always the venv's `bin/` directory. The binary there was installed by `pip install -e mcp/`, so it resolves to the working-tree code via the editable install — never a pipx or system copy.

If the binary isn't present (fresh clone that hasn't run `pip install -e mcp/`), the test should skip with a clear message rather than fall back to `$PATH`:

```python
@pytest.fixture(autouse=True)
def _require_binary():
    if not Path(ECHOFIT_MCP).exists():
        pytest.skip(f"echofit-mcp not installed at {ECHOFIT_MCP}")
```

Also isolate every writable path the subprocess might touch — `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `APP_USERS_PATH`, `ECHOFIT_DATA`, `ECHOFIT_CONFIG`. Otherwise tests pollute the developer's real dotfiles and can read stale state from earlier runs. See `tests/unit/cli/test_admin_cli_local.py::_env` for the canonical fixture.

### Running tests

```bash
python -m pytest
```

`pytest.ini` sets `testpaths = tests/unit tests/framework` and `asyncio_mode = strict`, so the default run covers both echofit's own tests and the free mission-critical tests imported from mcp-app. Integration tests (`tests/integration/`, `tests/cloud/`) are excluded from default runs and require real infrastructure.

## Multi-User Auth

EchoFit uses [mcp-app](https://github.com/krisrowe/mcp-app) for server bootstrapping and user-identity middleware. In HTTP mode:

- mcp-app's user-identity middleware validates the JWT and loads the full user record (auth + profile) in one store read, setting the `current_user` ContextVar
- `FileSystemUserDataStore` provides per-user directory storage
- `App.build_asgi()` composes MCP + auth + admin into one ASGI app
- Admin endpoints live at `/admin` — only MCP tools are visible to end users

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ECHOFIT_DATA` | Base data directory | `~/.local/share/echofit/` |
| `ECHOFIT_CONFIG` | Config directory | `~/.config/echofit/` |
| `ECHOFIT_SETTINGS` | Bootstrap settings file | `~/.config/echofit/settings.json` |
| `SIGNING_KEY` | JWT signing key (HTTP mode) | required, no default |
| `JWT_AUD` | Token audience validation | None (skip) |
| `APP_USERS_PATH` | Base data directory (checked before `ECHOFIT_DATA`; set in cloud deployments by gapp) | unset — `ECHOFIT_DATA` takes over |

## Code Conventions

- Python 3.10+
- Type hints on public methods
- Docstrings on MCP tools (user-centric, describe inputs/outputs/behavior)
- No hardcoded absolute paths — use env vars with XDG fallback
- DNS rebinding protection disabled (Cloud Run requirement)

### MCP tool docstrings are the only prompt

MCP tools must be fully self-describing. Do not rely on README.md, CONTRIBUTING.md, or any context file to explain tool behavior to the end user — those files are not present when a user installs the MCP server into their own project. All usage instructions, input/output descriptions, and behavioral guidance must live in the Python docstrings of the tool functions themselves.

### Tool permissions policy

When adding new MCP tools, classify them:

- **Safe tools** (read-only or append-only, e.g., `log_meal`, `get_food_log`) — can be auto-approved in client configurations for frictionless UX
- **Destructive tools** (modify or delete existing data, e.g., `revise_food_log_entry`, `remove_food_from_catalog`) — must never be auto-approved; require explicit user confirmation per invocation
