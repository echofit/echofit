from mcp_app import App

import echofit
from echofit import APP_NAME
from echofit_mcp.diet import tools as diet_tools

app = App(
    name=APP_NAME,
    tools_module=diet_tools,
    sdk_package=echofit,
)

__all__ = ["APP_NAME", "app"]
