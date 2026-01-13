# Food Agent

A specialized MCP agent for logging food consumption and managing a personal nutrition catalog. Designed for local use via stdio or remote deployment via Cloud Run.

## Overview

This project provides a Model Context Protocol (MCP) server that enables an AI assistant (like Gemini CLI) to:
1.  **Log Daily Meals:** Capture detailed nutritional data for food consumption.
2.  **Manage a Personal Catalog:** Curate a list of frequently eaten foods with verified nutritional info.
3.  **Cross-Platform Persistence:** Data stays synced between local and cloud environments via GCS FUSE.

## Quick Start: Local Personal Agent

This is the standard scenario for most users: running the agent locally.

### 1. Install
```bash
make install
```
*This installs the `food-agent` CLI and all dependencies.*

### 2. Register
```bash
# Registers with Gemini CLI as a stdio tool
gemini mcp add food-agent food-agent --stdio
```

### 3. Verify
Restart your Gemini session (`gemini -r`) and verify:
```bash
gemini mcp list
```

---

## Cloud Deployment

The following sections document the cloud hosting workflow, organized by persona.

### Admin Persona

Admins deploy and manage the cloud infrastructure. Requires `gcloud` CLI and GCP project access.

#### Initial Setup

```bash
# 1. Initialize admin config (discovers GCP project/bucket)
food-agent config init

# 2. Deploy services to Cloud Run
food-agent deploy
```

Configuration is saved to `~/.config/food-agent/admin.yaml`.

This provisions:
*   **Public Service:** `food-agent-mcp` (Authenticated via PAT)
*   **Private Service:** `food-agent-admin` (Authenticated via Google IAM)

#### User Management

```bash
# Add a new user
food-agent admin users add user@example.com --show-token

# List all users
food-agent admin users list

# Show user details (with token)
food-agent admin users show user@example.com --show-token

# Export config for handoff to end user
food-agent admin users export user@example.com > user-config.yaml
```

#### Admin-to-User Handoff

The `export` command generates a YAML file with the service URL and PAT that can be sent to the end user:

```bash
# Admin exports config
food-agent admin users export user@example.com > user-config.yaml

# Send user-config.yaml to the user via email, Slack, etc.
```

---

### User Persona

End users consume the service. No `gcloud` or admin access required.

#### Setup from Admin Handoff

```bash
# Import config received from admin (piped or redirected)
cat user-config.yaml | food-agent user import

# Or with overwrite behavior
cat user-config.yaml | food-agent user import --overwrite=force
cat user-config.yaml | food-agent user import --overwrite=fail
```

#### Manual Setup

```bash
# Configure credentials manually
food-agent user set --url https://YOUR-SERVICE-URL.run.app/ --pat YOUR_PAT
```

#### Verify & Use

```bash
# Show current config
food-agent user show

# View food log
food-agent user log show
food-agent user log show 2025-01-10
```

#### Gemini CLI Integration

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "food-agent": {
      "url": "https://YOUR-SERVICE-URL.run.app/",
      "headers": {
        "Authorization": "Bearer YOUR_PAT"
      }
    }
  }
}
```

#### Claude.ai / Other MCP Clients

Use URL-based auth:
```
https://YOUR-SERVICE-URL.run.app/?token=YOUR_PAT
```

---

## Configuration & Paths

The tool follows XDG conventions for configuration and data paths:

| File | Persona | Purpose |
|------|---------|---------|
| `~/.config/food-agent/admin.yaml` | Admin | GCP project, bucket, gcloud user |
| `~/.config/food-agent/user.yaml` | User | Service URL and PAT |
| `~/.local/share/food-agent/` | Both | Food log data |

Override with environment variables:
- `FOOD_AGENT_CONFIG` - Config directory
- `FOOD_AGENT_DATA` - Data directory

Refer to [docs/PATHS-DESIGN.md](docs/PATHS-DESIGN.md) for full architecture.

## Authentication Strategy

*   **Local (stdio):** Implicitly trusted (your local shell).
*   **Remote (HTTP/SSE):**
    *   **MCP Server:** Requires `Authorization: Bearer <PAT>`.
    *   **Admin API:** Requires Google Identity (OIDC) + Signed Shared Secret.

Refer to [food_agent/server/AUTH-DESIGN.md](food_agent/server/AUTH-DESIGN.md) for security details.

## Development

*   **Structure:**
    *   `food_agent/sdk/`: Shared business logic.
    *   `food_agent/mcp/`: Protocol definition.
    *   `food_agent/cli/`: Control Plane CLI.
    *   `food_agent/mcp_service/`: Public Cloud Run entrypoint.
    *   `food_agent/admin_service/`: Private Cloud Run entrypoint.
*   **Commands:**
    *   `make test`: Run verbose test suite.
    *   `make clean`: Remove build artifacts.
