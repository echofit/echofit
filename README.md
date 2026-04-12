# EchoFit

AI-powered fitness and nutrition tracking. Works locally via stdio (single user) or deployed as an HTTP service with multi-user auth.

## Modules

EchoFit is organized into feature modules that can be enabled or disabled independently:

| Module | Status | Description |
|--------|--------|-------------|
| **Diet** | Available | Daily food logging, nutrition catalog, calorie/macro/full nutrition tracking |
| **Workout** | Planned | Exercise logging with set-level data, exercise catalog |
| **Health** | Planned | Vitals tracking (blood pressure, etc.) |

Modules share a common config and user identity layer but do not depend on each other.

### Module configuration

Modules can be enabled at the server level or per-user. A deployment can expose all modules or a subset — for example, a "calorie counter" product surface that only enables diet tracking in calorie-only mode, while a "full fitness tracker" enables everything.

When a module is disabled for a user, its MCP tools are excluded from `tools/list` responses — the AI agent never sees them and never mentions them. This is controlled via:

- **Server-level:** Configuration in the deployment determines which modules are active for that instance
- **Per-user:** JWT claims can scope a user to specific modules, allowing different tiers or product surfaces from the same server

This means you can publish multiple products (e.g., "EchoFit Calorie Counter", "EchoFit Pro") to different connector stores, each pointing at the same server but with different module configurations via the client credentials or URL path.

Module toggling is a runtime concern, not a packaging or deployment concern. Every deployment includes all modules — `gapp deploy` produces the same artifact regardless of which product surface you're serving. What varies is the server configuration and JWT claims that control `tools/list` visibility.

## Packages

| PyPI package | Purpose | Install |
|-------------|---------|---------|
| `echofit-sdk` | Core library (all modules) | `pip install echofit-sdk` |
| `echofit-mcp` | MCP server for AI tools | `pipx install echofit-mcp` |
| `echofit` | CLI | `pipx install echofit` |

## Local Usage (stdio)

### Install

```bash
pip install -e sdk/ -e mcp/
```

### Register with an MCP client

**Claude Code:**
```bash
claude mcp add echofit -- echofit-mcp stdio --user local
```

**Gemini CLI:**
```bash
gemini mcp add echofit -- echofit-mcp stdio --user local
```

### Use

Start a conversation with your AI assistant and ask it to log food, show your food log, manage your catalog, etc.

## HTTP Deployment (multi-user)

For remote access from Claude.ai, mobile, or multiple devices, deploy as an HTTP service. The server uses [mcp-app](https://github.com/krisrowe/mcp-app) for server bootstrapping and user-identity middleware.

### Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SIGNING_KEY` | Yes (HTTP) | `dev-key` | JWT signing key |
| `JWT_AUD` | No | None (skip) | Token audience validation |
| `APP_USERS_PATH` | No | `~/.local/share/echofit/users/` | Per-user data directory |
| `MCP_PATH` | No | `/` | MCP endpoint path |

### Deploy with gapp

[gapp](https://github.com/krisrowe/gapp) deploys to Google Cloud Run with infrastructure, secrets, and GCS FUSE data volumes:

```bash
gapp init
gapp setup <project-id>
gapp deploy
```

See [gapp documentation](https://github.com/krisrowe/gapp) for details.

### Deploy without gapp

Any platform that runs Python ASGI apps works — Docker, Fly.io, Railway, etc. Set the environment variables above and run with uvicorn or any ASGI server.

### User management

The `echofit-mcp` package ships an `echofit-admin` CLI for registering users, issuing tokens, and checking service health. It talks to the `/admin` REST endpoints on the running server.

```bash
# Point the admin CLI at your deployment
echofit-admin connect https://YOUR-SERVICE-URL --signing-key "$SIGNING_KEY"

# Register a user and get their token
echofit-admin users add alice@example.com
echofit-admin tokens create alice@example.com

# List / revoke
echofit-admin users list
echofit-admin users revoke alice@example.com

# Health check
echofit-admin health
```

The token printed by `tokens create` is what the end user puts in their MCP client config (see below).

For local development against the filesystem store, use `echofit-admin connect local` instead of a URL.

### MCP client configuration

**Claude Code / Gemini CLI (Authorization header):**
```json
{
  "mcpServers": {
    "echofit": {
      "url": "https://YOUR-SERVICE-URL/",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

**Claude.ai (query param):**
```
https://YOUR-SERVICE-URL/?token=YOUR_TOKEN
```

## Configuration

### Timezone and day boundary

`sdk/echofit/app.yaml` configures when the calendar day rolls over:

```yaml
hours_offset: 4
timezone: "America/Chicago"
```

`hours_offset: 4` means eating at 2 AM counts as the prior day (the new day starts at 4 AM). Adjustable for any schedule.

### Data paths

Local data follows XDG conventions:
- Data: `~/.local/share/echofit/`
- Config: `~/.config/echofit/`

Override with `ECHOFIT_DATA` and `ECHOFIT_CONFIG` env vars.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture, testing conventions, and how to add features.

### Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e sdk/ -e 'mcp/[test]' -e cli/
python -m pytest
```

The `[test]` extra pulls in `pytest`, `pytest-asyncio`, and `httpx` — required to run the free mission-critical tests that the mcp-app framework provides against this solution. See [CONTRIBUTING.md](CONTRIBUTING.md#testsframework--free-tests-from-mcp-app-that-verify-mission-critical-functionality) for what those tests verify.

### Dependencies

- [mcp-app](https://github.com/krisrowe/mcp-app) — MCP server framework with user-identity middleware
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol SDK
- PyYAML — configuration
