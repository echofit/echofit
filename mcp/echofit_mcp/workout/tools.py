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


async def get_workout_log(
    limit: int = 5,
    unit: str = "sessions",
    exercise: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict[str, Any]:
    """Show the workout log, most recent first.

    This always starts from the most recent workout that exists and walks
    backward — it does not need and should not be given a specific date.
    Use it for every "show my log" / "what have I been doing" / "my last N
    <exercise>" question.

    Args:
        limit: How many most-recent results to return (default 5).
        unit: "sessions" returns the most recent dates with data, each with
            its entries grouped together. "entries" returns the most recent
            individual entries (newest first), each tagged with its date —
            use this for "my last 4 curls".
        exercise: Optional exercise name to filter by (e.g. "Curls"). When
            given, the result also includes a summary with the count and the
            average/max weight and reps over the matched entries.
        since: Optional inclusive start date (YYYY-MM-DD), e.g. for
            "workouts in the last two weeks" (caller supplies the date).
        until: Optional inclusive end date (YYYY-MM-DD). Pass the day before
            the oldest result you've already seen to page further back.

    Returns:
        sessions or entries: The results, most recent first.
        count: How many were returned.
        has_more: Whether more results exist past this page.
        scan_truncated: True if the search was capped before fully
            satisfying the request — tell the user it only looked back
            through 'scanned_through' and offer to look further.
        scanned_through: The oldest month examined (YYYY-MM).
    """
    return sdk.get_workout_log(
        limit=limit, unit=unit, exercise=exercise, since=since, until=until
    )


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


async def move_workout_entries(
    entry_ids: List[str],
    source_date: str,
    target_date: str,
) -> dict[str, Any]:
    """Move one or more workout entries from one date to another.

    Use this to correct the date of a logged workout — e.g. you logged
    today but the workout actually happened yesterday. Entries are
    identified by ID and moved to the target date; the entries on the
    source date that you did not name are left untouched.

    Returns the post-move total_entries for both the source and target
    dates so you know the resulting state without re-reading.

    Args:
        entry_ids: IDs of the entries to move.
        source_date: The date the entries are currently on (YYYY-MM-DD).
        target_date: The date to move them to (YYYY-MM-DD).
    """
    return sdk.move_workout_entries(entry_ids, source_date, target_date)
