import os
from typing import List, Optional, Dict, Any, Union

from mcp.server.fastmcp import FastMCP
from app_user import create_app, FileSystemUserDataStore, DataStoreAuthAdapter

from food_agent import APP_NAME
from food_agent.sdk.core import FoodAgentSDK

# Initialize MCP server
mcp_path = os.environ.get("MCP_PATH", "/")
mcp = FastMCP(APP_NAME, stateless_http=True, json_response=True, streamable_http_path=mcp_path)

# DNS rebinding — disable for Cloud Run
mcp.settings.transport_security.enable_dns_rebinding_protection = False

# Data store and SDK
store = FileSystemUserDataStore(app_name=APP_NAME)
auth_store = DataStoreAuthAdapter(store)
sdk = FoodAgentSDK()

# HTTP mode — ASGI app with auth + admin
app = create_app(store=auth_store, inner_app=mcp.streamable_http_app())


@mcp.tool()
async def log_meal(
    food_entries: List[dict],
) -> dict[str, Any]:
    """Log food consumption. Entries are recorded against the current date
    as determined by the server's configured timezone and day-boundary
    offset. The date is never specified by the caller — it is always
    computed automatically. The response includes the effective date so
    you can confirm or inform the user which calendar day was used.

    Args:
        food_entries: A list of food entry objects, each containing
            food_name, user_description, standard_serving, consumed,
            and confidence_score per the food-log schema.

    Returns:
        success: Whether the entries were saved.
        date: The calendar date the entries were logged against (YYYY-MM-DD).
        entries_added: Number of new entries added.
        total_entries: Total entries on that date after adding.
    """
    return sdk.log_food(food_entries)


@mcp.tool()
async def get_food_log(
    entry_date: Optional[str] = None,
    include: str = "all",
    filter: Optional[Union[str, List[str]]] = None,
    use_regex: bool = False
) -> dict[str, Any]:
    """Retrieve the user's food log for a given date.

    If no date is provided, returns the log for today (using the
    configured timezone and day-boundary offset).

    Args:
        entry_date: Optional date in YYYY-MM-DD format. Defaults to
            the current effective date.
        include: "all" to return individual items and totals, or
            "totals" to return only the nutrition summary.
        filter: Optional search term(s) to match against food names
            and descriptions. Supports glob patterns (* and ?).
        use_regex: If true, treat filter values as regular expressions
            instead of glob/substring patterns.

    Returns:
        date: The date of the log.
        items: List of food entries (omitted when include="totals").
        totals: Aggregated nutrition totals for the day.
    """
    return sdk.get_food_log(entry_date, include, filter, use_regex)


@mcp.tool()
async def show_food_catalog(
    filter: Optional[Union[str, List[str]]] = None,
    use_regex: bool = False
) -> dict[str, Any]:
    """Browse the user's saved food catalog.

    The catalog contains reusable food definitions with standard
    serving sizes and nutrition data.

    Args:
        filter: Optional search term(s) to match against food names.
            Supports glob patterns (* and ?).
        use_regex: If true, treat filter values as regular expressions.

    Returns:
        items: List of catalog entries.
        count: Total number of matching items.
    """
    return sdk.get_catalog(filter, use_regex)


@mcp.tool()
async def add_food_to_catalog(food_item: Dict) -> dict[str, Any]:
    """Add a new food to the user's catalog for future reuse.

    The food_name must be unique in the catalog. If the food already
    exists, use update_food_in_catalog instead.

    Args:
        food_item: A food definition including food_name,
            standard_serving (with size and nutrition), and any
            other fields from the food-log schema.

    Returns:
        success: Whether the food was added.
        message: Confirmation with the food name.
    """
    return sdk.add_to_catalog(food_item)


@mcp.tool()
async def update_food_in_catalog(food_name: str, updates: Dict) -> dict[str, Any]:
    """Update an existing food in the user's catalog.

    Matches by food_name (case-insensitive). Only the provided fields
    are updated; other fields are preserved.

    Args:
        food_name: The name of the food to update.
        updates: A dict of fields to update (e.g. standard_serving).

    Returns:
        success: Whether the update was applied.
        message: Confirmation with the food name.
    """
    return sdk.update_catalog_item(food_name, updates)


@mcp.tool()
async def remove_food_from_catalog(food_name: str) -> dict[str, Any]:
    """Remove a food from the user's catalog.

    Args:
        food_name: The name of the food to remove (case-insensitive).

    Returns:
        success: Whether the food was removed.
        message: Confirmation with the food name.
    """
    return sdk.remove_from_catalog(food_name)


@mcp.tool()
async def revise_food_log_entry(
    food_name: str,
    updates: Dict,
    entry_date: Optional[str] = None
) -> dict[str, Any]:
    """Revise the details of a previously logged food entry.

    Use this to correct nutrition data, serving sizes, or descriptions.
    To move an entry to a different date, use move_food_log_entries
    instead.

    Args:
        food_name: The exact food_name of the entry to revise.
        updates: A dict of fields to update on the entry.
        entry_date: The date the entry is on, in YYYY-MM-DD format.
            Defaults to the current effective date.

    Returns:
        success: Whether the revision was applied.
        message: How many entries were updated.
        date: The date of the revised log.
    """
    return sdk.revise_log_entry(food_name, updates, entry_date)


@mcp.tool()
async def move_food_log_entries(
    entry_ids: List[str],
    source_date: str,
    target_date: str,
) -> dict[str, Any]:
    """Move one or more food log entries from one date to another.

    This is the only way to reassign entries to a different calendar
    date. Use get_food_log to find the entry IDs you need to move.

    Args:
        entry_ids: List of entry IDs to move (from the "id" field on
            each log entry).
        source_date: The date the entries are currently on (YYYY-MM-DD).
        target_date: The date to move them to (YYYY-MM-DD).

    Returns:
        success: Whether the entries were moved.
        message: Summary of what was moved.
        moved_entries: Names of the moved food items.
        source_date: The original date.
        target_date: The new date.
    """
    return sdk.move_log_entries(entry_ids, source_date, target_date)


@mcp.tool()
async def get_food_log_settings() -> dict[str, Any]:
    """Show the current food log configuration.

    Returns the effective settings including defaults for any values
    not explicitly configured. Useful for understanding what timezone
    and day-boundary rules are in effect, and what date the system
    considers "today".

    Returns:
        timezone: The IANA timezone used for date calculations
            (e.g. "America/Chicago").
        hours_offset: How many hours past midnight the new calendar
            day begins. For example, 4 means food eaten before 4 AM
            counts as the prior day. Negative values shift the
            boundary earlier (e.g. -2 means the next day starts at
            10 PM).
        effective_date: The current effective date (YYYY-MM-DD) based
            on the timezone and offset rules.
    """
    return sdk.get_settings()


@mcp.tool()
async def set_food_log_data_folder(path: Optional[str] = None) -> dict[str, Any]:
    """Set or reset the folder where food log data is stored.

    Args:
        path: Absolute or ~-relative path to use for data storage.
            Pass null or omit to reset to the default (XDG data home).

    Returns:
        success: Whether the change was applied.
        message: The resolved path or confirmation of reset.
    """
    return sdk.set_data_folder(path)


def run_server():
    """Run the MCP server with stdio transport."""
    mcp.run()

if __name__ == "__main__":
    run_server()
