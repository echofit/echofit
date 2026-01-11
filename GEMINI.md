# Agent Context (User Assistance)

This section guides the AI assistant in interacting with the user.

*   **Meal Logging Trigger:** If the user describes an amount of food (e.g., "an apple and 2 slices of bread" or "5 saltine crackers"), assume they want that logged. You should proceed to resolve the items (checking the catalog first) and then log them using the `log_meal` tool.
*   **Food-Related Queries:** For any food-related prompt or question, always evaluate which `food-agent` tool (e.g., `show_food_catalog`, `get_food_log`) can best assist the user.

---

# Repository Context (Contributor Guide)

This section guides developers contributing to the `food-agent` repository.

## Overview

This repository houses the **Food Agent**, an MCP server designed to help users track their daily food intake and manage a personal nutritional catalog.

**Crucial Design Principle:**
The MCP tools defined here must be **self-describing**. Do not rely on this file (`GEMINI.md`) to instruct the AI on how to use the tools, as this file will not be present in the context of a user utilizing the installed tools in a different project. All usage instructions, schema definitions, and behavioral guidance must reside within the **Python docstrings** of the tools themselves.

## Architecture

The project follows a layered architecture to ensure separation of concerns:

1.  **SDK Layer (`food_agent/sdk/`):**
    *   Contains the core business logic (logging, catalog management, file I/O).
    *   Handles configuration and path resolution (`config.py`).
    *   **Goal:** Reusable, testable Python code independent of the MCP protocol.

2.  **MCP Layer (`food_agent/mcp/`):**
    *   Defines the MCP server and exposes tools.
    *   **Goal:** Thin wrapper around the SDK. Responsible strictly for interface definition and docstrings.

## Core Workflows (Developer Support)

Developers contributing to this repo should maintain support for these primary user stories:
*   **Logging:** Users describe a meal (natural language) -> Agent resolves items -> `log_meal` (structured JSON).
*   **Retrieval:** Users ask "What did I eat?" -> `get_food_log` (returns items + calculated totals).
*   **Cataloging:** Users verify nutrition -> `add_food_to_catalog` (builds local database).

## Tool Permissions Policy

When adding new capabilities, adhere to this policy regarding `.gemini/settings.json`:

*   **Safe Tools (Auto-Approve):** Read-only or append-only tools (e.g., `log_meal`, `get_food_log`) should be added to the allowed list to enable a frictionless UX.
*   **Destructive Tools (Gate):** Tools that modify existing records or change settings (e.g., `update_food_in_catalog`, `set_food_log_data_folder`) must **never** be auto-approved.

## Nutrition Data Policy

To ensure consistency across clients (CLI, Web, Mobile) and adherence to industry standards (see [DESIGN.md](DESIGN.md) for research and rationale):

1.  **Backend Rounding (Source of Truth):** The SDK/API is responsible for returning "display-ready" nutritional values. Clients should NOT implement their own rounding logic.
2.  **FDA Compliance:** All nutritional values (Calories, Macros, etc.) must be rounded according to FDA 21 CFR 101.9 standards before being returned in a log or total.
3.  **Calculation Order:** Daily totals must be calculated from the **precise** (unrounded) values of individual items and then rounded once at the end. This maintains maximum accuracy while providing a clean UI.

## Development & Verification

### Setup
```bash
make install
```

### Verification
After making changes, verify the server starts and the tools are registered:
1.  `timeout 2s food-agent` (Ensure no immediate crash)
2.  `gemini mcp list` (Ensure `food-agent` is connected)

### Contributing
*   **Docstrings:** When updating tool signatures, update the docstring immediately. This is the only "prompt" the end-user agent receives.
*   **Versioning:** Ensure `setup.py` and `Makefile` are kept in sync.

## Quick Start for Contributors

After cloning the repo, you can quickly set up your environment by running:

```bash
/setup
```

This slash command (defined in `.gemini/commands/setup.toml`) will guide you through installing dependencies and registering the MCP server.