from typing import List, Optional, Dict, Any, Union
from mcp.server.fastmcp import FastMCP
from food_agent.sdk.core import FoodAgentSDK

# Initialize MCP server in Stateless HTTP mode (Recommended for Production)
mcp = FastMCP("food-agent", stateless_http=True, json_response=True, streamable_http_path="/")

# Configure Transport Security (DNS Rebinding Protection)
import os
allowed_hosts = os.environ.get("MCP_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
mcp.settings.transport_security.allowed_hosts = [h.strip() for h in allowed_hosts]
mcp.settings.transport_security.enable_dns_rebinding_protection = False

# Initialize SDK
sdk = FoodAgentSDK()

@mcp.tool()
async def log_meal(
    food_entries: List[dict],
    entry_date: Optional[str] = None
) -> dict[str, Any]:
    return sdk.log_food(food_entries, entry_date)

@mcp.tool()
async def get_food_log(
    entry_date: Optional[str] = None,
    include: str = "all",
    filter: Optional[Union[str, List[str]]] = None,
    use_regex: bool = False
) -> dict[str, Any]:
    return sdk.get_food_log(entry_date, include, filter, use_regex)

@mcp.tool()
async def show_food_catalog(
    filter: Optional[Union[str, List[str]]] = None,
    use_regex: bool = False
) -> dict[str, Any]:
    return sdk.get_catalog(filter, use_regex)

@mcp.tool()
async def add_food_to_catalog(food_item: Dict) -> dict[str, Any]:
    return sdk.add_to_catalog(food_item)

@mcp.tool()
async def update_food_in_catalog(food_name: str, updates: Dict) -> dict[str, Any]:
    return sdk.update_catalog_item(food_name, updates)

@mcp.tool()
async def remove_food_from_catalog(food_name: str) -> dict[str, Any]:
    return sdk.remove_from_catalog(food_name)

@mcp.tool()
async def revise_food_log_entry(
    food_name: str,
    updates: Dict,
    entry_date: Optional[str] = None
) -> dict[str, Any]:
    return sdk.revise_log_entry(food_name, updates, entry_date)

@mcp.tool()
async def set_food_log_data_folder(path: Optional[str] = None) -> dict[str, Any]:
    return sdk.set_data_folder(path)

def run_server():
    """Run the MCP server with stdio transport."""
    mcp.run()

if __name__ == "__main__":
    run_server()