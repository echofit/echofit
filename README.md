# EchoFit

AI-powered fitness and nutrition tracking. Works locally via stdio (single user) or deployed as an HTTP service with multi-user auth.

## Modules

EchoFit is organized into feature modules that can be enabled or disabled independently:

| Module | Status | Description |
|--------|--------|-------------|
| **Diet** | Available | Daily food logging, nutrition catalog, calorie/macro/full nutrition tracking |
| **Workout** | Available | Exercise logging with set-level data, exercise catalog |
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

For remote access from Claude.ai, Claude Desktop, mobile, or multiple devices, deploy as an HTTP service. The server uses [mcp-app](https://github.com/echomodel/mcp-app) for server bootstrapping and standard MCP authorization: users sign in with your identity provider, the server validates the access tokens it issues, and the server holds no secret of its own.

### Environment variables

| Variable | Required | If missing | Purpose |
|----------|----------|------------|---------|
| `AUTH_ISSUER` | Yes (HTTP) | Startup fails | The identity provider's issuer identifier, exactly as in the access token's `iss` claim (trailing slash included if the issuer uses one) |
| `ADMIN_EMAILS` | Yes (HTTP) | No administrators; startup warns | Comma-separated emails that may call `/admin`. Each is also admitted as a user on first sign-in, which is how a fresh deployment bootstraps |
| `AUTH_EMAIL_CLAIM` | No | `email` | Claim that carries the user's email. Issuers that namespace custom claims need the full claim name |
| `AUTH_ADMISSION` | No | `allowlist` | Who is admitted on first sign-in besides administrators: `allowlist` (registered users only) or `open` (anyone the provider signs in) |
| `MAX_USERS` | No | Unlimited | With `open` admission, the number of user records past which new sign-ins get `403` |
| `AUTH_AUDIENCE` | No | Derived from the request `Host` | Value the token's `aud` must contain. Set only when the service is reached by address rather than hostname, or answers on several hostnames |
| `APP_USERS_PATH` | No | `~/.local/share/echofit/users/` | Per-user data directory. Point it at persistent storage in any durable deployment |

None of these is a secret. `AUTH_ISSUER` must match the token's `iss` byte for byte; a missing or extra trailing slash is the usual mistake. The startup log line `mcp_app.startup auth` echoes what the server is using.

### Identity provider

Any OAuth 2.1 authorization server that MCP clients can register with works. Set it up once per deployment:

1. Create an API (resource) whose identifier is the server's public URL exactly as users type it, trailing slash included (for example `https://YOUR-SERVICE-URL/`). Turn refresh tokens ("offline access") on.
2. Pick the login method your users should see (Sign in with Google is a common choice) and turn off any you don't use, such as password login.
3. Enable dynamic client registration (or client ID metadata documents) so MCP clients register with the server URL alone. `<issuer>/.well-known/oauth-authorization-server` must list a `registration_endpoint` and `S256` under `code_challenge_methods_supported`.
4. Put the user's email in access tokens. Some providers (Auth0, for one) only allow that under a namespaced claim name; echofit's convention for those is `https://echofit.ai/email`, and `AUTH_EMAIL_CLAIM` names whatever claim your provider actually writes.
5. If the issuer needs a default audience to issue JWT (not opaque) access tokens when a client sends `resource` rather than `audience`, set it to the API identifier.
6. If the provider treats dynamically registered clients as third-party applications that need explicit API access (Auth0 does), grant them default user-delegated access to the API; otherwise sign-in fails before the login page appears.

### Deploy

Any platform that runs a Python process works. The process is one command under the environment variables above:

```bash
pip install ./sdk ./mcp
AUTH_ISSUER=https://YOUR-ISSUER/ ADMIN_EMAILS=you@example.com \
APP_USERS_PATH=/data/users echofit-mcp serve --port 8080
```

Wrap that in whatever your platform expects (a container image, a systemd unit, a buildpack). Set `AUTH_EMAIL_CLAIM` too if your provider namespaces the email claim. Mount persistent storage at `APP_USERS_PATH`; anything less loses user data on restart. Behind a proxy or load balancer, forward `Host` and `X-Forwarded-Proto` unchanged so the server derives the public URL users type.

**Shortcut: gapp.** [gapp](https://github.com/echomodel/gapp) deploys to Google Cloud Run with infrastructure, secrets, and GCS FUSE data volumes, and this repo carries a reference `gapp.yaml`. gapp has no channel for operator-supplied plain values outside the repo, so the two deployment-specific values are declared as user-provided secrets and set once before the first deploy:

```bash
gapp init
gapp setup <project-id>
gapp secrets set auth-issuer       # prompts; the issuer URL, trailing slash included
gapp secrets set admin-emails      # prompts; the comma-separated list
gapp deploy
```

See the [gapp documentation](https://github.com/echomodel/gapp) for details.

### Connect the admin CLI

The `echofit-mcp` package ships an `echofit-admin` CLI. Point it at the deployment; the URL is all it needs, and it is saved in `~/.config/echofit/setup.json`:

```bash
echofit-admin connect https://YOUR-SERVICE-URL
echofit-admin health
```

Against a deployment the CLI supports `connect`, `health`, `probe`, and `register`. `users`, `tools`, and `safe-tool` need a signed-in administrator, which the CLI cannot yet do remotely; they work in full against the local store (`echofit-admin connect local`).

### Sanity-check the deployment

```bash
echofit-admin probe
```

`probe` hits `/health`, reads the public discovery document at `/.well-known/oauth-protected-resource`, and confirms that an unauthenticated MCP request gets the `401` challenge an MCP client follows to sign in. It must report `OAuth: ok` with the issuer you configured and a `resource` equal to the URL users type. A different `resource` means the front door is rewriting `Host` or dropping `X-Forwarded-Proto`; fix the proxy or pin `AUTH_AUDIENCE`.

### Who can sign in

- Emails in `ADMIN_EMAILS` are admitted on first sign-in and may call `/admin`.
- With `AUTH_ADMISSION=open`, anyone the identity provider signs in is admitted and registered on their first request, until `MAX_USERS` records exist. echofit owns its users' data and needs nothing from them to start, so this is the natural setting for a deployment that anyone with an account may use; the reference `gapp.yaml` sets it with a cap of 25.
- Under the default `allowlist` policy, anyone else needs a user record first. Register one with an administrator's access token from the identity provider:

  ```bash
  curl -X POST https://YOUR-SERVICE-URL/admin/users \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"email": "alice@example.com"}'
  ```

- Everyone else can sign in at the identity provider but gets `403` from the server: "not registered" under `allowlist`, "not accepting new users" once an open deployment reaches its cap.

Revoking a user deletes the record (`DELETE /admin/users/{email}`); their next request is a `403`. The identity provider owns the tokens themselves.

### Connect end users

```bash
echofit-admin register
```

prints the registration command for each MCP client. No command carries a credential, so the same output serves every user; each signs in with their own account on first use.

**Claude Code:**
```bash
claude mcp add --transport http -s user echofit https://YOUR-SERVICE-URL/
```

**Antigravity CLI (agy):**
```bash
agy mcp add echofit https://YOUR-SERVICE-URL/
```

**Claude.ai, Claude Desktop, and Claude mobile:** Settings → Connectors → Add custom connector, with the URL `https://YOUR-SERVICE-URL/`. The client discovers the issuer from the server URL, registers itself, and opens the sign-in page.

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
pip install -e sdk/ -e 'mcp/[test]'
python -m pytest
```

The `[test]` extra pulls in `pytest`, `pytest-asyncio`, and `httpx` — required to run the free mission-critical tests that the mcp-app framework provides against this solution. See [CONTRIBUTING.md](CONTRIBUTING.md#testsframework--free-tests-from-mcp-app-that-verify-mission-critical-functionality) for what those tests verify.

### Dependencies

- [mcp-app](https://github.com/echomodel/mcp-app) — MCP server framework with user-identity middleware
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol SDK
- PyYAML — configuration
