from mcp_app import App

import echofit
from echofit import APP_NAME
from echofit_mcp import tools

app = App(
    name=APP_NAME,
    tools_module=tools,
    sdk_package=echofit,
)

__all__ = ["APP_NAME", "app"]
