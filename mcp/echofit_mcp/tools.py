"""Aggregated MCP tools from all EchoFit modules.

Workaround: mcp-app's App accepts a single tools_module, so this
module re-exports all public async tool functions from each feature
module. Remove this file if mcp-app adds multi-module support.
See: https://github.com/echomodel/mcp-app/issues/TBD
"""

# Diet tools
from echofit_mcp.diet.tools import (  # noqa: F401
    log_meal,
    get_food_log,
    show_food_catalog,
    add_food_to_catalog,
    update_food_in_catalog,
    remove_food_from_catalog,
    revise_food_log_entry,
    move_food_log_entries,
    get_food_log_settings,
)

# Workout tools
from echofit_mcp.workout.tools import (  # noqa: F401
    log_workout,
    get_workout_log,
    list_exercises,
    add_exercise,
    update_exercise,
    remove_exercise,
    revise_workout_entry,
    remove_workout_entry,
)
