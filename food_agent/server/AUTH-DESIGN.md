# Authentication & Architecture Design

## Overview
The system is split into two distinct Cloud Run services to separate public-facing agent interaction from sensitive user management.

## 1. Public MCP Server (`food-agent-mcp`)
*   **Access:** Publicly accessible on the internet.
*   **Authentication:** Personal Access Token (PAT).
*   **Header Standard:** `Authorization: Bearer <YOUR_PAT>` (Aligned with RFC 6750 and GitHub standards).
*   **Mechanism:**
    *   On startup/request, checks a cached copy of `users.csv` from Google Cloud Storage (GCS).
    *   If the token in the header matches a valid PAT in the list, the request is allowed.
    *   If the token is unknown, the server refreshes the cache from GCS. If still unknown, returns `403 Forbidden`.
*   **Infrastructure:**
    *   Runs as Service Account: `mcp-sa`
    *   Permissions: `storage.objects.get` on the `users.csv` bucket.

## 2. Private Admin Service (`food-agent-admin`)
*   **Access:** Restricted. Requires Google IAM Authentication (OIDC).
*   **Authentication:** Dual-Layer.
    1.  **Google Identity (IAM):** Caller must present a valid Google ID Token. Cloud Run IAM policy restricts invoker access.
    2.  **Shared Secret:** Caller must present a secret in the `X-Admin-Secret` header.
*   **Mechanism:**
    *   `POST /admin/users`: Registers a new user/PAT.
    *   `GET /admin/users/{email}`: Retrieves details.
    *   Updates the `users.csv` file in GCS.
*   **Infrastructure:**
    *   Runs as Service Account: `admin-sa`
    *   Permissions: `storage.objects.get`, `storage.objects.create` (rewrite) on the `users.csv` bucket.

## 3. Storage (GCS)
*   **Bucket:** Labeled with `ai-food-log=default`.
*   **Content:** `users.csv` containing `pat,email`.
*   **Security:** No public access. Only accessible by `mcp-sa` (Read) and `admin-sa` (Read/Write).

## 4. Secret Management: Admin Shared Secret
To ensure the Admin API is robust against unauthorized access even if IAM is misconfigured, we use a **Shared Secret** layer.

### Lifecycle
1.  **Generation:** Terraform generates a random 32-character high-entropy string using `random_password`.
2.  **Storage:** The secret is stored **only** in the Terraform State and injected into the Admin Cloud Run service environment as `ADMIN_SHARED_SECRET`. It is **not** stored in local `.env` or versioned files.
3.  **Discovery (Admin CLI):** To register a user, the Admin CLI tool fetches the current secret at runtime by querying the Cloud Run service configuration (via `gcloud run services describe`). This ensures that the administrator (You) always has the correct secret without manual syncing.

## 5. Deployment Logic
*   **CLI (`food_agent.cli`):**
    *   Discovers the GCP Project ID and GCS Bucket by label `ai-food-log=default`.
    *   Caches these resource IDs locally in `~/.config/food-agent/deploy_context.json`.
*   **Terraform:**
    *   Provisions the two Cloud Run services.
    *   Creates the GCS bucket if missing.
    *   Generates and injects the Admin Shared Secret.
    *   Creates the Service Accounts and binds specific IAM roles.
