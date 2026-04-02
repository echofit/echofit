"""Food agent MCP tools — pure async functions calling SDK.

Discovered by mcp-app framework from mcp-app.yaml tools: food_agent.mcp.tools
No framework imports. Docstrings become MCP tool descriptions.
Type hints become tool schemas.
"""

from typing import List, Optional, Dict, Any, Union
from food_agent.sdk.core import FoodAgentSDK

sdk = FoodAgentSDK()


async def log_meal(food_entries: List[dict]) -> dict[str, Any]:
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


async def get_food_log(
    entry_date: Optional[str] = None,
    include: str = "all",
    filter: Optional[Union[str, List[str]]] = None,
    use_regex: bool = False,
) -> dict[str, Any]:
    """Retrieve the user's food log for a given date.

    If no date is provided, returns the log for today (using the
    configured timezone and day-boundary offset).

    Args:
        entry_date: Optional date in YYYY-MM-DD format.
        include: "all" to return individual items and totals, or
            "totals" to return only the nutrition summary.
        filter: Optional search term(s) to match against food names.
        use_regex: If true, treat filter values as regular expressions.
    """
    return sdk.get_food_log(entry_date, include, filter, use_regex)


async def show_food_catalog(
    filter: Optional[Union[str, List[str]]] = None,
    use_regex: bool = False,
) -> dict[str, Any]:
    """Browse the user's saved food catalog."""
    return sdk.get_catalog(filter, use_regex)


async def add_food_to_catalog(food_item: Dict) -> dict[str, Any]:
    """Add a new food to the user's catalog for future reuse."""
    return sdk.add_to_catalog(food_item)


async def update_food_in_catalog(food_name: str, updates: Dict) -> dict[str, Any]:
    """Update an existing food in the user's catalog."""
    return sdk.update_catalog_item(food_name, updates)


async def remove_food_from_catalog(food_name: str) -> dict[str, Any]:
    """Remove a food from the user's catalog."""
    return sdk.remove_from_catalog(food_name)


async def revise_food_log_entry(
    food_name: str,
    updates: Dict,
    entry_date: Optional[str] = None,
) -> dict[str, Any]:
    """Revise the details of a previously logged food entry."""
    return sdk.revise_log_entry(food_name, updates, entry_date)


async def move_food_log_entries(
    entry_ids: List[str],
    source_date: str,
    target_date: str,
) -> dict[str, Any]:
    """Move one or more food log entries from one date to another."""
    return sdk.move_log_entries(entry_ids, source_date, target_date)


async def get_food_log_settings() -> dict[str, Any]:
    """Show the current food log configuration."""
    return sdk.get_settings()
