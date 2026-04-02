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
  context.py                   # User identity (re-exports from mcp-app)
  app.yaml                     # Timezone and day boundary config
  diet/                        # Diet tracking module
    core.py                    # DietSDK — logging, catalog, entry management
    rounding.py                # FDA nutrition rounding

mcp/echofit_mcp/               # echofit-mcp package
  diet/
    tools.py                   # MCP tool definitions — thin async wrappers

cli/echofit_cli/               # echofit (CLI) package
  main.py                      # Click CLI commands
  cloud.py                     # Cloud deployment utilities
```

If you're writing logic in an MCP tool or CLI command, stop and move it to the SDK.

### Modules

EchoFit is organized into feature modules within the SDK. Each module has a parallel structure in the MCP and CLI layers:

- `echofit.diet` — diet/nutrition tracking (SDK)
- `echofit_mcp.diet` — MCP tools for diet (thin wrappers)
- `echofit.workout` — exercise logging (future)
- `echofit_mcp.workout` — MCP tools for workout (future)

Modules do not import each other. They share `echofit.config` and `echofit.context` for user identity and data path resolution. Adding a module = add a subdir in `sdk/echofit/`, add a corresponding subdir in `mcp/echofit_mcp/`, optionally add CLI commands.

Diet and workout share a **daily journal of entries** pattern — one log file per day, entries appended, same CRUD operations (log, revise, move between dates, filter). Where possible, shared infrastructure (date handling, entry ID generation, daily log file management) should be reused across these modules rather than duplicated. Health/vitals (e.g., blood pressure tracking) will have different data structures and access patterns — reads are more analytical (trends over time) and writes may not follow the daily-entries model. There is a need to be thoughtful about allowing for reuse and code consolidation at higher or lower levels in the user data model depending upon need. Three modules might share a common part of the echofit (or broader echomodel) user data storage framework, while only two of those three share a more specific element of a user data framework — e.g., logged entries in a journal that's typically viewed and managed in daily terms.

All modules ship together in `echofit-sdk` — there are no per-module packages (no `echofit-diet`, `echofit-workout`). Module visibility is controlled at runtime via server config and JWT claims, not at install time. See the README for details on module configuration.

### SDK returns dicts

SDK methods return JSON-serializable dicts. Both MCP tools and CLI commands use the same return values. MCP tools return them directly. CLI formats for humans.

### User identity and data path resolution

User identity flows via `current_user_id` ContextVar (re-exported from `mcp_app.context`).

**Two modes:**

| Mode | Transport | `current_user_id` | Data path |
|------|-----------|-------------------|-----------|
| **Single-user (stdio)** | stdio | `"default"` | `~/.local/share/echofit/` |
| **Multi-user (HTTP)** | HTTP/SSE | Set from JWT `sub` claim by mcp-app middleware | `~/.local/share/echofit/{user}` (or `APP_USERS_PATH/{user}` in cloud) |

In stdio mode, the user identity is `"default"` and data goes directly to the base data directory — no user subdirectory. In HTTP mode, mcp-app's user-identity middleware extracts the user from the JWT and sets `current_user_id`, which causes `get_app_data_dir()` to return a user-scoped subdirectory.

The SDK reads `current_user_id` — it never imports MCP or transport-layer code. This means all modules (diet, workout, etc.) get user-scoped data for free without knowing how the user was identified.

## Adding Features

1. **SDK first** — implement in `sdk/echofit/<module>/` (e.g., `sdk/echofit/workout/core.py`)
2. **MCP tools** — add thin async wrappers in `mcp/echofit_mcp/<module>/tools.py`
3. **CLI commands** (optional) — add a Click command group in `cli/echofit_cli/`
4. **Tests** — add sociable unit tests in `tests/unit/sdk/`, transport tests in `tests/unit/mcp/` or `tests/unit/cli/`

## Testing

### Philosophy: sociable unit tests

Tests verify complete features or SDK transactions end-to-end. No mocks unless needed for network I/O. Isolate via temp dirs and env vars — the same env vars the solution reads in production.

### Test directory structure

```
tests/
  unit/                        # Fast, offline, no credentials (DEFAULT)
    sdk/                       # SDK business logic tests — the bulk of tests
      test_diet_core.py
      test_user_data_paths.py
    mcp/                       # MCP transport tests (no network)
      test_diet_tools.py
    cli/                       # CLI transport tests
      test_cloud_config.py
  integration/                 # Requires running server (NEVER default)
    test_mcp_stdio.py
  cloud/                       # Requires cloud deployment (NEVER default)
    test_in_cloud.py
    test_admin_cloud_security.py
```

### What to test where

**`tests/unit/sdk/`** — The bulk of all tests. Test SDK methods directly. Cover business logic, data persistence, date/timezone handling, catalog CRUD, entry management. These call SDK classes with `current_user_id` set manually and `ECHOFIT_DATA`/`ECHOFIT_CONFIG` pointed at temp dirs.

**`tests/unit/mcp/`** — A small number of transport-level tests. These call MCP tool functions directly (they're just async functions — no server, no network). They prove:
- Tool functions correctly delegate to SDK
- User identity resolution works: set `current_user_id` to different values and verify data lands in the right directory
- Single-user (`"default"`) vs multi-user (`"user@example.com"`) data path isolation

**`tests/unit/cli/`** — CLI command tests using Click's `CliRunner`. No subprocess calls, no network. Test that commands parse arguments correctly and call the right SDK methods.

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
    token = current_user_id.set("alice@example.com")
    try:
        sdk = DietSDK()
        sdk.log_food([...])
        assert (tmp_env / "alice~example.com" / "daily").exists()
    finally:
        current_user_id.reset(token)

    token = current_user_id.set("bob@example.com")
    try:
        sdk = DietSDK()
        sdk.log_food([...])
        assert (tmp_env / "bob~example.com" / "daily").exists()
    finally:
        current_user_id.reset(token)

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

### Running tests

```bash
python -m pytest tests/unit/ -v
```

Integration tests (`tests/integration/`, `tests/cloud/`) are excluded from default runs and require real infrastructure.

## Multi-User Auth

EchoFit uses [mcp-app](https://github.com/krisrowe/mcp-app) for server bootstrapping and user-identity middleware. In HTTP mode:

- mcp-app's user-identity middleware extracts `current_user_id` from the JWT `sub` claim
- `FileSystemUserDataStore` provides per-user directory storage
- `create_app()` composes MCP + auth + admin into one ASGI app
- Admin endpoints live at `/admin` — only MCP tools are visible to end users

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ECHOFIT_DATA` | Base data directory | `~/.local/share/echofit/` |
| `ECHOFIT_CONFIG` | Config directory | `~/.config/echofit/` |
| `ECHOFIT_SETTINGS` | Bootstrap settings file | `~/.config/echofit/settings.json` |
| `SIGNING_KEY` | JWT signing key (HTTP mode) | `dev-key` |
| `JWT_AUD` | Token audience validation | None (skip) |
| `APP_USERS_PATH` | Per-user data directory (cloud) | `~/.local/share/echofit/users/` |
| `MCP_PATH` | MCP endpoint path | `/` |

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
