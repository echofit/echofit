from mcp_app.cli import create_admin_cli, create_mcp_cli

from echofit import APP_NAME
from echofit_mcp.diet import tools as diet_tools

mcp_cli = create_mcp_cli(APP_NAME, tools_module=diet_tools)
admin_cli = create_admin_cli(APP_NAME)

__all__ = ["APP_NAME", "mcp_cli", "admin_cli"]
