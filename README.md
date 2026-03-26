# Food Agent

MCP server for food consumption logging and personal nutrition catalog management. Works locally via stdio (single user) or deployed as an HTTP service with multi-user auth.

## Features

- **Daily food logging** with timezone-aware date boundaries and configurable day cutoff
- **Nutrition catalog** for reusable food definitions with standard servings
- **Entry management** — log, revise, move between dates, filter by name/pattern
- **Per-user data scoping** when deployed as a multi-user HTTP service

## Local Usage (stdio)

### Install

```bash
pip install -e .
```

### Register with an MCP client

**Claude Code:**
```bash
claude mcp add food-agent -- python -m food_agent.mcp.server
```

**Gemini CLI:**
```bash
gemini mcp add food-agent -- python -m food_agent.mcp.server
```

### Use

Start a conversation with your AI assistant and ask it to log food, show your food log, manage your catalog, etc.

## HTTP Deployment (multi-user)

For remote access from Claude.ai, mobile, or multiple devices, deploy as an HTTP service. The server uses [app-user](https://github.com/krisrowe/app-user) for JWT-based auth and user management.

### Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SIGNING_KEY` | Yes (HTTP) | `dev-key` | JWT signing key |
| `JWT_AUD` | No | None (skip) | Token audience validation |
| `APP_USERS_PATH` | No | `~/.local/share/food-agent/users/` | Per-user data directory |
| `MCP_PATH` | No | `/` | MCP endpoint path |

### Run locally over HTTP

```bash
SIGNING_KEY=dev-key uvicorn food_agent.mcp.server:app
```

### Deploy with gapp

[gapp](https://github.com/krisrowe/gapp) deploys to Google Cloud Run with infrastructure, secrets, and GCS FUSE data volumes. The fastest way to get started is the gapp Claude Code plugin — ask **"help me deploy this app"** and it walks you through everything:

```bash
claude plugin marketplace add https://github.com/krisrowe/claude-plugins.git
claude plugin marketplace update claude-plugins
claude plugin install gapp@claude-plugins --scope user
```

Or use the CLI directly:

```bash
gapp init
gapp setup <project-id>
gapp deploy
```

See [gapp documentation](https://github.com/krisrowe/gapp) for details.

### Deploy without gapp

Any platform that runs Python ASGI apps works — Docker, Fly.io, Railway, etc. Set the environment variables above and run:

```bash
uvicorn food_agent.mcp.server:app --host 0.0.0.0 --port 8080
```

### User management

After deployment, use the [app-user](https://github.com/krisrowe/app-user) CLI or plugin to register users and manage access. Admin operations go through `/admin` REST endpoints on the running server.

### MCP client configuration

**Claude Code / Gemini CLI (Authorization header):**
```json
{
  "mcpServers": {
    "food-agent": {
      "url": "https://YOUR-SERVICE-URL/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

**Claude.ai (query param):**
```
https://YOUR-SERVICE-URL/mcp?token=YOUR_TOKEN
```

## Configuration

### Timezone and day boundary

`food_agent/app.yaml` configures when the calendar day rolls over:

```yaml
hours_offset: 4
timezone: "America/Chicago"
```

`hours_offset: 4` means eating at 2 AM counts as the prior day (the new day starts at 4 AM). Adjustable for any schedule.

### Data paths

Local data follows XDG conventions:
- Data: `~/.local/share/food-agent/`
- Config: `~/.config/food-agent/`

Override with `FOOD_AGENT_DATA` and `FOOD_AGENT_CONFIG` env vars.

## Development

### Structure

```
food_agent/
  __init__.py         # APP_NAME constant
  sdk/                # All business logic
    core.py           # Food logging, catalog, entry management
    config.py         # Timezone, paths, XDG resolution
    context.py        # User identity (re-exports from app-user)
  mcp/
    server.py         # MCP tool definitions (thin wrappers over SDK)
  cli/                # Optional CLI commands
```

All behavior lives in the SDK. MCP tools and CLI commands are thin wrappers.

### Tests

```bash
python -m pytest tests/unit/ -v
```

Sociable unit tests — no mocks, isolated via temp dirs and env vars.

### Dependencies

- [mcp](https://github.com/modelcontextprotocol/python-sdk) — FastMCP server framework
- [app-user](https://github.com/krisrowe/app-user) — JWT auth, user management, per-user data storage
- PyYAML — configuration
