"""EchoFit Workout MCP tools — pure async functions calling SDK."""

from typing import List, Optional, Dict, Any
from echofit.workout import WorkoutSDK

sdk = WorkoutSDK()


async def log_workout(exercises: List[dict]) -> dict[str, Any]:
    """Log workout exercises. Entries are recorded against today's date
    (using the configured timezone and day-boundary offset).

    Args:
        exercises: A list of exercise entries. Each entry should contain:
            - exercise_name (str): name of the exercise
            - sets (int): number of sets performed
            - weight (float, optional): weight used in lbs
            - max_reps (int, optional): max reps achieved in any set
            - notes (str, optional): free-text notes

    Returns:
        success: Whether the entries were saved.
        date: The calendar date logged against (YYYY-MM-DD).
        entries_added: Number of new entries added.
        total_entries: Total entries on that date after adding.
    """
    return sdk.log_workout(exercises)


async def get_workout_log(entry_date: Optional[str] = None) -> dict[str, Any]:
    """Retrieve the workout log for a given date.

    If no date is provided, returns the log for today (using the
    configured timezone and day-boundary offset).

    Args:
        entry_date: Optional date in YYYY-MM-DD format.
    """
    return sdk.get_workout_log(entry_date)


async def list_exercises(
    target: Optional[str] = None, lookback_days: int = 14
) -> dict[str, Any]:
    """Browse the exercise catalog with last-performed dates.

    Each exercise includes a last_performed date drawn from recent
    workout logs. Results are sorted most-recently-performed first.

    Args:
        target: Optional muscle group filter (e.g. "chest", "arms", "back").
        lookback_days: How many days back to scan for last-performed
            dates. Defaults to 14.
    """
    return sdk.list_exercises(target, lookback_days)


async def add_exercise(name: str, targets: Optional[str] = None) -> dict[str, Any]:
    """Add a new exercise to the catalog.

    Args:
        name: Exercise name (e.g. "Bench Press").
        targets: Target muscle group (e.g. "Chest", "Arms", "Back").
    """
    return sdk.add_exercise(name, targets)


async def update_exercise(name: str, updates: Dict) -> dict[str, Any]:
    """Update an exercise in the catalog (e.g. rename or change target group).

    Args:
        name: Current name of the exercise.
        updates: Fields to update (e.g. {"name": "New Name", "targets": "Legs"}).
    """
    return sdk.update_exercise(name, updates)


async def remove_exercise(name: str) -> dict[str, Any]:
    """Remove an exercise from the catalog.

    Args:
        name: Name of the exercise to remove.
    """
    return sdk.remove_exercise(name)


async def revise_workout_entry(
    entry_id: str,
    updates: Dict,
    entry_date: Optional[str] = None,
) -> dict[str, Any]:
    """Revise a previously logged workout entry.

    Args:
        entry_id: The ID of the entry to revise.
        updates: Fields to update (e.g. {"sets": 3, "weight": 135}).
        entry_date: Optional date in YYYY-MM-DD format (defaults to today).
    """
    return sdk.revise_workout_entry(entry_id, updates, entry_date)


async def remove_workout_entry(
    entry_id: str,
    entry_date: Optional[str] = None,
) -> dict[str, Any]:
    """Remove a workout entry from the log.

    Args:
        entry_id: The ID of the entry to remove.
        entry_date: Optional date in YYYY-MM-DD format (defaults to today).
    """
    return sdk.remove_workout_entry(entry_id, entry_date)
