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

## The Deployment Journey (Cloud Hosting)

We provide a professional-grade, free-tier eligible workflow to host your agent on Google Cloud using the **official recommended Stateless HTTP transport** for optimal scalability.

### Phase 1: Initialize Configuration
...
### Phase 3: Deploy to Cloud Run
...
*   **Public Service:** `food-agent-mcp` (Authenticated via PAT).
    *   **Transport:** Stateless HTTP (JSON-RPC over POST).
    *   **Security:** DNS Rebinding protection configured via `MCP_ALLOWED_HOSTS`.
*   **Private Service:** `food-agent-admin` (Authenticated via Google IAM).

## Configuration & Paths

The tool follows a 3-tier fallback routine for resolving configuration and data paths:
1.  **Primary:** Environment Variables (`FOOD_AGENT_CONFIG`, `FOOD_AGENT_DATA`).
2.  **Secondary:** Bootstrap file (`~/.config/food-agent/settings.json`).
3.  **Tertiary:** XDG Defaults (`~/.config/food-agent`, `~/.local/share/food-agent`).

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
