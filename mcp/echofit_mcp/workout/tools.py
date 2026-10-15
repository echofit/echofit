"""EchoFit Workout MCP tools — pure async functions calling SDK."""

from typing import List, Optional, Dict, Any
from echofit.workout import WorkoutSDK

sdk = WorkoutSDK()


async def log_workout(exercises: List[dict]) -> dict[str, Any]:
    """Log workout exercises. Entries are recorded against today's date
    (using the configured timezone and day-boundary offset).

    Every exercise_name must match an exercise in the catalog
    (case-insensitive); the call is rejected, with the unknown names
    listed, before anything is written. Check list_exercises first, and
    add_exercise for a genuinely new movement.

    Args:
        exercises: A list of exercise entries. Each entry should contain:
            - exercise_name (str): name of the exercise, as in the catalog
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


async def search_workouts(
    since: Optional[str] = None,
    until: Optional[str] = None,
    days: Optional[int] = None,
    exercises: Optional[List[str]] = None,
    min_weight: Optional[float] = None,
    max_weight: Optional[float] = None,
    min_reps: Optional[int] = None,
    max_reps: Optional[int] = None,
    workouts: int = 5,
    sort: Optional[List[Dict[str, str]]] = None,
    fields: Optional[List[str]] = None,
    stats: bool = False,
) -> dict[str, Any]:
    """Search the workout log: the most recent matching workouts, with optional exact stats.

    This is the one tool for reading more than a single entry. Use it for
    "show my log", "what did I do today / this week", "my last 10 curls",
    and — with stats=true — for every question that needs numbers over a
    period: personal records, sets at each weight, how reps moved, how
    many sessions, "is this the most reps I've done at this weight".

    A WORKOUT is all the sets logged on one calendar day: a morning and
    an evening visit on the same date are one workout. With filters, a
    workout is a day with at least one matching row, and the page is
    every matching row from the `workouts` most recent such days. So
    "my last 10 curls" means exercises=["Curls"], workouts=10: the ten
    most recent days you curled, with all the curl rows from each. A page
    never splits a day.

    A ROW is one logged exercise entry (sets, weight, max_reps, notes),
    not a single set. Each row also carries est_1rm, an Epley estimated
    one-rep max (weight × (1 + reps/30), only when weight and reps are
    present and reps ≤ 12): a score for comparing sets of the SAME
    exercise across different weight/rep combinations. Never compare
    est_1rm between different exercises.

    STATS are computed over EVERY matching row in the period, whatever
    `workouts` is; `workouts` only caps the rows returned. workouts=0 with
    stats=true is a pure stats call. Without stats, the read is cheap and
    stops as soon as it has the page.

    Recipes:
      today's workout:        since=<today>, until=<today>   (or days=1)
      recent log:             workouts=5                      (the default)
      last 10 curls:          exercises=["Curls"], workouts=10
      curls, 6-month review:  exercises=["Curls"], days=180, stats=true, workouts=0
                              → stats[0].by_weight: sets, min/max reps at each weight
      all-time PR:            exercises=["Curls"], stats=true, workouts=0
                              → stats[0].best_est_1rm and by_weight[0]; then, to see
                              the rows: min_weight=<that weight>, sort=[{"by":"max_reps"}]
      heaviest sets at 8+:    exercises=["Curls"], min_reps=8, workouts=10,
                              sort=[{"by":"weight"},{"by":"max_reps"}]
      everything at 60 lbs:   exercises=["Curls"], min_weight=60, max_weight=60, stats=true
      what have I trained:    days=30, stats=true, workouts=0   (one stats block per exercise)
      compact rows:           fields=["date","exercise_name","weight","max_reps"]
      page further back:      until=<day before oldest_date from the last response>
      oldest first:           sort=[{"by":"date","dir":"asc"}]  (orders the page; the page is
                              still the most recent workouts — page back with until)

    Args:
        since: Inclusive start date (YYYY-MM-DD). With neither since nor
            days, the whole history is in range.
        until: Inclusive end date (YYYY-MM-DD).
        days: The last N calendar days up to today; a shortcut for since.
            Do not pass both days and since. Not the same as workouts.
        exercises: Optional list of exercise names, matched to the catalog
            case-insensitively. A name not in the catalog is an error
            (call list_exercises to see the catalog). Omit for all.
        min_weight / max_weight: Inclusive weight bounds (lbs). Rows with
            no weight are excluded when either is set.
        min_reps / max_reps: Inclusive bounds on a row's max_reps. Rows
            with no reps are excluded when either is set.
        workouts: How many most-recent matching dates to return rows for
            (default 5). Every matching row on those dates is returned, so
            count varies. There is no cap, but every row costs context:
            prefer stats=true for totals and page for detail.
        sort: Order of the rows in the page: a list of {"by": field,
            "dir": "asc"|"desc"} applied in order; dir defaults to "desc".
            Fields: "date", "weight", "max_reps", "sets", "exercise_name",
            "est_1rm". Missing values sort last; ties fall back to newest
            first. Default: newest first. sort orders the page; it does
            not change which workouts are in it (always the most recent),
            and stats do not depend on it.
        fields: Which fields to include per row, from "id", "date",
            "exercise_name", "sets", "weight", "max_reps", "est_1rm",
            "notes". Default all. Keep "id" if you may revise or remove.
        stats: True to compute per-exercise aggregates over the full
            period (reads every month in range once).

    Returns:
        rows / count: The page's rows and how many.
        workouts / newest_date / oldest_date: How many dates the page
            covers and its bounds. oldest_date is the paging cursor.
        has_more: Older matching workouts exist beyond this page (with
            stats, they are already counted in the stats). To get them,
            call again with until = the day before oldest_date. Days are
            never split across pages, so nothing is skipped or repeated.
            Notes often say how a weight was counted (per arm vs total,
            equipment), so read them before comparing weights.
        period: The since/until actually applied (days resolves to since).
        With stats=true:
          total_rows / sessions: Across all exercises in the period.
          stats: One block per exercise (in the order asked, or most rows
            first when exercises was omitted) — exercise, total_rows,
            total_sets, sessions, first_date, last_date, max_weight,
            max_reps, best_est_1rm {est_1rm, weight, max_reps, date}, and
            by_weight: one row per distinct weight, heaviest first —
            weight, sets, rows, min_reps, max_reps, first_date, last_date.
            by_weight is the full picture: a weight tried once shows up
            next to the working weight, so say both.
        months_scanned / scanned_through: How far back the read went.
    """
    return sdk.search_workouts(
        since=since, until=until, days=days, exercises=exercises,
        min_weight=min_weight, max_weight=max_weight,
        min_reps=min_reps, max_reps=max_reps,
        workouts=workouts, sort=sort, fields=fields, stats=stats,
    )


async def audit_exercise_names() -> dict[str, Any]:
    """Check that every exercise name in the workout log matches the catalog.

    Every logged entry stores an exercise name, and new entries must match
    a catalog exercise. This reads the whole log once and reports entries
    whose stored name is not in the catalog (orphans — typically older
    entries logged before the check existed, or a spelling variant) and
    entries whose spelling differs from the catalog's only in case.

    Returns:
        clean: True when the log and catalog agree completely.
        orphans: [{exercise_name, entries}] — names with no catalog match,
            most entries first. Fix with rename_logged_exercise(old_name,
            new_name) into the right catalog exercise, or add_exercise if
            the name is genuinely a new exercise.
        case_mismatches: [{exercise_name, catalog_name, entries}] — same
            exercise, different capitalisation. Fix the same way.
        catalog_count / logged_names: Sizes of the two sides.
    """
    return sdk.audit_exercise_names()


async def rename_logged_exercise(old_name: str, new_name: str) -> dict[str, Any]:
    """Rewrite every workout log entry named old_name to the catalog exercise new_name.

    Use it to merge an orphaned or misspelled name reported by
    audit_exercise_names into the correct catalog exercise, or to fold a
    duplicate exercise into another (then remove_exercise the duplicate).
    It rewrites history, so confirm with the user first and show them the
    audit counts.

    Args:
        old_name: The name as currently stored in the log (case-insensitive).
            It does not need to be in the catalog.
        new_name: The catalog exercise to rename to. Must exist in the
            catalog; entries are stored with the catalog's exact spelling.

    Returns:
        entries_changed / shards_changed: How many log entries and month
            files were rewritten. Zero means nothing was stored under
            old_name.
    """
    return sdk.rename_logged_exercise(old_name, new_name)


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

    Renaming (updates["name"]) also rewrites every log entry that used the
    old name, so history stays attached to the exercise; the response's
    log_entries_renamed says how many. Renaming onto a name that already
    exists is refused — merge with rename_logged_exercise instead.

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
