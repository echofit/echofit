"""Free tests against this echofit app sourced from the mcp-app framework.

These tests verify mission-critical operational functionality that the
mcp-app framework provides to every solution built on it — user auth,
user admin, JWT enforcement, admin CLI flows, app wiring, HTTP health,
and SDK test-coverage auditing. None of them were written in echofit.
They are imported from `mcp_app.testing.*` and run against echofit's
`App` object via the `app` fixture in `conftest.py`.

If any of these fails, something mission-critical in echofit is broken
even though echofit's own business logic may be untouched — a framework
subsystem has regressed, and production is at risk. Read the failure
message and fix the implementation; never edit these imports.

Layout mirrors the upstream package structure. Each line pulls in one
subsystem's tests:

  iam     — identity & access (auth enforcement, admin CLI local, errors)
  wiring  — App object, entry points, tool protocol sanity
  tools   — SDK test-coverage audit for every public tool
  health  — HTTP health endpoint

Do NOT add echofit-specific assertions to this file. Business logic
belongs in `tests/unit/sdk/`.
"""

from mcp_app.testing.iam.test_auth_enforcement import *  # noqa: F401,F403
from mcp_app.testing.iam.test_admin_local import *  # noqa: F401,F403
from mcp_app.testing.iam.test_admin_errors import *  # noqa: F401,F403
from mcp_app.testing.wiring.test_app_wiring import *  # noqa: F401,F403
from mcp_app.testing.tools.test_sdk_coverage_audit import *  # noqa: F401,F403
from mcp_app.testing.health.test_health import *  # noqa: F401,F403
