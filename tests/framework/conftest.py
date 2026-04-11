"""Fixture wiring for the free mcp-app framework tests.

The only thing echofit has to supply to the framework test modules
is the `App` object. This file returns it. Everything else — binary
paths, environment isolation, HTTP clients, admin subprocess
helpers — is handled by fixtures inside `mcp_app.testing.*`.

Background:
  - echomodel/mcp-app#11 — App composition-root design
  - echofit/echofit#4 — adoption tracker
"""

import pytest

from echofit_mcp import app as echofit_app


@pytest.fixture(scope="session")
def app():
    return echofit_app
