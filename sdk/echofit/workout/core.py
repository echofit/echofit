import json
import logging
from pathlib import Path
from datetime import timedelta
from typing import List, Dict, Optional, Any

from echofit.config import EchoFitConfig
from echofit.journal import DailyJournal

logger = logging.getLogger(__name__)


class WorkoutSDK:
    def __init__(self, config: Optional[EchoFitConfig] = None):
        self.config = config or EchoFitConfig()
        # The workout log is a month-sharded journal; all storage, the
        # add/revise/remove/move operations, the reverse-cursor reads, and
        # the uniform output contract live in the shared provider.
        self._journal = DailyJournal(
            self.config,
            subdir="workouts",
            name_field="exercise_name",
            legacy_suffix="_workout.json",
        )

    # ── data paths ──────────────────────────────────────────────

    @property
    def _exercise_catalog_file(self) -> Path:
        return self.config.data_dir / "catalog" / "exercises.json"

    def _ensure_dirs(self):
        self._exercise_catalog_file.parent.mkdir(parents=True, exist_ok=True)

    # ── exercise catalog ────────────────────────────────────────

    def _load_exercises(self) -> List[Dict]:
        if not self._exercise_catalog_file.exists():
            return []
        try:
            with open(self._exercise_catalog_file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Bad JSON in {self._exercise_catalog_file}")
            return []

    def _save_exercises(self, exercises: List[Dict]):
        with open(self._exercise_catalog_file, "w") as f:
            json.dump(exercises, f, indent=2)

    def list_exercises(
        self, target: Optional[str] = None, lookback_days: int = 14
    ) -> Dict[str, Any]:
        """Return the exercise catalog with last-performed dates.

        Each exercise includes a ``last_performed`` field (YYYY-MM-DD or
        null) derived from workout logs within the lookback window.
        Results are sorted most-recently-performed first; exercises not
        performed in the window sort to the end.
        """
        exercises = self._load_exercises()
        if target:
            exercises = [
                e for e in exercises
                if target.lower() in (e.get("targets") or "").lower()
            ]

        # Enrich with stats from recent workout logs
        stats = self._exercise_stats(lookback_days)

        for ex in exercises:
            s = stats.get(ex["name"].lower(), {})
            ex["last_performed"] = s.get("last_performed")
            ex["last_weight"] = s.get("last_weight")
            ex["last_reps"] = s.get("last_reps")
            ex["max_weight"] = s.get("max_weight")
            ex["max_reps"] = s.get("max_reps")

        exercises.sort(
            key=lambda e: e["last_performed"] or "",
            reverse=True,
        )

        return {"exercises": exercises, "count": len(exercises)}

    def _days_in_window(self, cutoff: str):
        """Yield (date_str, entries) for dates >= cutoff, reading only the
        month shards that overlap the window (bounded I/O on gcsfuse)."""
        months, _ = self._journal._select_months(
            since=cutoff, until=None, max_active_months=None
        )
        for month in months:
            shard = self._journal.load_shard(month)
            for date_str, entries in shard.items():
                if date_str >= cutoff:
                    yield date_str, entries

    def _exercise_stats(self, lookback_days: int) -> Dict[str, Dict]:
        """Scan workout logs and return per-exercise stats.

        Returns {exercise_name_lower: {last_performed, last_weight,
        last_reps, max_weight, max_reps}} from the lookback window.
        """
        today = self.config.get_effective_today()
        cutoff = (today - timedelta(days=lookback_days)).isoformat()
        stats: Dict[str, Dict] = {}

        for date_str, entries in self._days_in_window(cutoff):
            for entry in entries:
                name = (entry.get("exercise_name") or "").lower()
                if not name:
                    continue

                weight = entry.get("weight")
                reps = entry.get("max_reps")

                if name not in stats:
                    stats[name] = {
                        "last_performed": None,
                        "last_weight": None,
                        "last_reps": None,
                        "max_weight": None,
                        "max_reps": None,
                    }

                s = stats[name]

                # last_performed / last_weight / last_reps: from most recent date
                if s["last_performed"] is None or date_str >= s["last_performed"]:
                    s["last_performed"] = date_str
                    if weight is not None:
                        s["last_weight"] = weight
                    if reps is not None:
                        s["last_reps"] = reps

                # max_weight / max_reps: across entire lookback
                if weight is not None:
                    if s["max_weight"] is None or weight > s["max_weight"]:
                        s["max_weight"] = weight
                if reps is not None:
                    if s["max_reps"] is None or reps > s["max_reps"]:
                        s["max_reps"] = reps

        return stats

    def add_exercise(self, name: str, targets: Optional[str] = None) -> Dict[str, Any]:
        """Add an exercise to the catalog."""
        self._ensure_dirs()
        exercises = self._load_exercises()
        for ex in exercises:
            if ex["name"].lower() == name.lower():
                return {"error": f"Exercise '{name}' already exists. Use update_exercise instead."}
        entry = {"name": name}
        if targets:
            entry["targets"] = targets
        exercises.append(entry)
        self._save_exercises(exercises)
        return {"success": True, "message": f"Added '{name}' to exercise catalog."}

    def update_exercise(self, name: str, updates: Dict) -> Dict[str, Any]:
        """Update an exercise in the catalog (e.g. rename or change targets)."""
        self._ensure_dirs()
        exercises = self._load_exercises()
        for ex in exercises:
            if ex["name"].lower() == name.lower():
                ex.update(updates)
                self._save_exercises(exercises)
                return {"success": True, "message": f"Updated '{name}'."}
        return {"error": f"Exercise '{name}' not found."}

    def remove_exercise(self, name: str) -> Dict[str, Any]:
        """Remove an exercise from the catalog."""
        exercises = self._load_exercises()
        before = len(exercises)
        exercises = [e for e in exercises if e["name"].lower() != name.lower()]
        if len(exercises) == before:
            return {"error": f"Exercise '{name}' not found."}
        self._save_exercises(exercises)
        return {"success": True, "message": f"Removed '{name}' from exercise catalog."}

    # ── workout logging (delegated to the shared daily journal) ──

    def log_workout(self, exercises: List[Dict]) -> Dict[str, Any]:
        """Log workout exercises for today (append-only).

        Entries are recorded against the effective current date (configured
        timezone + day-boundary offset), never replacing existing entries.

        Each exercise dict should contain:
          - exercise_name (str): name matching the exercise catalog
          - sets (int): number of sets performed
          - weight (float, optional): weight used (lbs)
          - max_reps (int, optional): max reps achieved in any set
          - notes (str, optional): free-text notes

        Returns the resolved ``date``, ``entries_added``, the new
        ``total_entries`` for that date, and the assigned ``ids``.
        """
        return self._journal.append(exercises)

    def get_workout_log(
        self,
        limit: int = 5,
        unit: str = "sessions",
        exercise: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        max_active_months: int = 12,
    ) -> Dict[str, Any]:
        """Read the workout log as a reverse-chronological cursor.

        Always starts from the most recent data that exists and walks
        backward — it never needs to know today's date. Use it for
        "show my recent workouts" (sessions) or "my last N curls" (entries).

        Args:
            limit: how many most-recent results to return.
            unit: "sessions" (dates with data, grouped) or "entries"
                (individual entries, newest first).
            exercise: optional exercise name to filter by.
            since: optional inclusive lower-bound date (YYYY-MM-DD).
            until: optional inclusive upper-bound date (YYYY-MM-DD).
            max_active_months: cap on how many most-recent months-with-data
                are scanned when no since/until is given, bounding I/O.

        When ``exercise`` is given, the result also includes a ``summary``
        (n, avg/max weight, avg max-reps, last values) over the matched
        entries. If the scan was capped before satisfying the request,
        ``scan_truncated`` is true.
        """
        result = self._journal.query(
            limit=limit,
            unit=unit,
            name=exercise,
            since=since,
            until=until,
            max_active_months=max_active_months,
        )
        if exercise and "error" not in result:
            if unit == "entries":
                matched = result.get("entries", [])
            else:
                matched = [e for s in result.get("sessions", []) for e in s["entries"]]
            result["summary"] = self._summarize(exercise, matched)
        return result

    @staticmethod
    def _summarize(exercise: str, entries: List[Dict]) -> Dict[str, Any]:
        """Aggregate matched entries (already newest-first) for one exercise."""
        weights = [e["weight"] for e in entries if e.get("weight") is not None]
        reps = [e["max_reps"] for e in entries if e.get("max_reps") is not None]
        return {
            "exercise": exercise,
            "n": len(entries),
            "avg_weight": round(sum(weights) / len(weights), 1) if weights else None,
            "max_weight": max(weights) if weights else None,
            "avg_max_reps": round(sum(reps) / len(reps), 1) if reps else None,
            "last_weight": weights[0] if weights else None,
            "last_max_reps": reps[0] if reps else None,
        }

    def migrate_storage(self) -> Dict[str, Any]:
        """One-time fold of legacy per-date files into month shards.

        Idempotent — safe to call repeatedly; a no-op once migration is done.
        """
        return self._journal.migrate_legacy_day_files()

    def revise_workout_entry(
        self, entry_id: str, updates: Dict, entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Revise a previously logged workout entry by ID (defaults to today)."""
        return self._journal.revise(entry_id, updates, entry_date)

    def remove_workout_entry(
        self, entry_id: str, entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Remove a workout entry by ID (defaults to today)."""
        return self._journal.remove(entry_id, entry_date)

    def move_workout_entries(
        self, entry_ids: List[str], source_date: str, target_date: str
    ) -> Dict[str, Any]:
        """Move workout entries (by ID) from one date to another.

        Entries are appended to the target date before being removed from
        the source, so an interrupted move never loses data. Echoes the
        post-move ``total_entries`` for both dates.

        Args:
            entry_ids: IDs of the entries to move.
            source_date: date the entries are currently on (YYYY-MM-DD).
            target_date: date to move them to (YYYY-MM-DD).
        """
        return self._journal.move(entry_ids, source_date, target_date)
