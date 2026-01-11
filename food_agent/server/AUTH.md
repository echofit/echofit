# Authentication Strategy

## Overview
This document outlines the authentication mechanism used to secure the Food Agent MCP server when deployed as an HTTP/SSE service.

## Chosen Strategy: HTTP Bearer Authentication
We use standard **Bearer Token Authentication** (RFC 6750) to protect the server endpoints.

### Mechanism
1.  **Shared Secret:** A high-entropy secret token is generated and shared between the server (via environment variable `MCP_AUTH_TOKEN`) and the authorized client.
2.  **Transport Security:** Requests are authenticated at the HTTP transport layer before reaching the MCP protocol handler.
3.  **Validation:**
    *   The server inspects the `Authorization` HTTP header.
    *   Format: `Authorization: Bearer <token>`
    *   If the header is missing or the token does not match, the request is rejected with `401 Unauthorized` or `403 Forbidden`.

### Rationale
*   **Simplicity:** Does not require a complex Identity Provider (IdP) or OAuth2 flow for a single-user personal agent.
*   **Compatibility:** Supported by virtually all HTTP clients and easily configurable in MCP client settings.
*   **Statelessness:** Aligns with the stateless nature of the MCP protocol's HTTP transport.

### Configuration
*   **Server:** Set `MCP_AUTH_TOKEN` in the `.env` file (injected at runtime).
*   **Client:** Configure your MCP client (e.g., Claude Desktop, Gemini) to send the header:
    ```json
    "headers": {
      "Authorization": "Bearer <YOUR_SECRET_TOKEN>"
    }
    ```

## Alternatives Considered

### mTLS (Mutual TLS)
*   **Pros:** Extremely secure; verified at the socket layer.
*   **Cons:** High operational complexity (certificate management/rotation); difficult to configure in some consumer MCP clients.
*   **Verdict:** Rejected due to excessive friction for a personal project.

### Google IAP (Identity-Aware Proxy)
*   **Pros:** Managed zero-trust access; utilizes Google Accounts.
*   **Cons:** Requires Google Cloud Load Balancing (GCLB) which incurs significant monthly costs (~$18/mo minimum), violating the "Free Tier" design goal.
*   **Verdict:** Rejected due to cost.

### OAuth2 / OIDC
*   **Pros:** Standard for multi-user apps; enables scope-based permissions.
*   **Cons:** Requires running or connecting to an Auth Server; adds significant code complexity for handling flows/callbacks.
*   **Verdict:** Overkill for a single-user application.

## Accounting for Future Requirements: Token Invalidation

To support token management (issuance and revocation) without a heavy database, we plan to evolve the strategy to use **Signed JWTs** with a file-based **Revocation List**.

### Proposed Architecture

1.  **Provisioning (Bootstrap):**
    *   **Endpoint:** `/provision`
    *   **Input:** Valid Google ID Token (OIDC) verifying user identity.
    *   **Output:** A signed JWT (Personal Access Token) valid for ~30 days.
    *   **Claims:** `email`, `iat` (issued at), `exp` (expiration).

2.  **Validation Middleware:**
    *   **Step 1:** Verify JWT signature using server secret.
    *   **Step 2:** Verify `exp` (standard expiry check).
    *   **Step 3:** **Revocation Check.**
        *   Read `config/revocation.csv`.
        *   Format: `email,iat_invalid_before`
        *   Logic: If `token.iat` < `iat_invalid_before` for that email, **REJECT**.

3.  **Logout / Invalidation:**
    *   **Endpoint:** `/logout` (Authenticated via Google ID Token or valid PAT).
    *   **Action:** Updates `config/revocation.csv`.
    *   **Logic:** Sets `iat_invalid_before` for the user to the current timestamp.
    *   **Effect:** Immediately invalidates all tokens issued prior to that moment.

### Data Storage (`revocation.csv`)
A simple, scalable text file:
```csv
email,iat_invalid_before
worker@company.com,2026-01-10T12:00:00Z
test@example.com,2026-01-11T00:00:00Z
```