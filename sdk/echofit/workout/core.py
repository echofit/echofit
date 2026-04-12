import json
import logging
import uuid
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Any

from echofit.config import EchoFitConfig

logger = logging.getLogger(__name__)


class WorkoutSDK:
    def __init__(self, config: Optional[EchoFitConfig] = None):
        self.config = config or EchoFitConfig()

    # ── data paths ──────────────────────────────────────────────

    @property
    def _workout_log_dir(self) -> Path:
        return self.config.data_dir / "workouts"

    @property
    def _exercise_catalog_file(self) -> Path:
        return self.config.data_dir / "catalog" / "exercises.json"

    def _ensure_dirs(self):
        self._workout_log_dir.mkdir(parents=True, exist_ok=True)
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

    def _exercise_stats(self, lookback_days: int) -> Dict[str, Dict]:
        """Scan workout logs and return per-exercise stats.

        Returns {exercise_name_lower: {last_performed, last_weight,
        last_reps, max_weight, max_reps}} from the lookback window.
        """
        today = self.config.get_effective_today()
        cutoff = today - timedelta(days=lookback_days)
        stats: Dict[str, Dict] = {}

        if not self._workout_log_dir.exists():
            return stats

        for path in sorted(self._workout_log_dir.glob("*_workout.json")):
            date_str = path.name.split("_")[0]
            try:
                log_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if log_date < cutoff:
                continue

            try:
                with open(path, "r") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

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

    # ── workout logging ─────────────────────────────────────────

    def _log_file(self, d: str) -> Path:
        return self._workout_log_dir / f"{d}_workout.json"

    def _load_log(self, d: str) -> List[Dict]:
        path = self._log_file(d)
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Bad JSON in {path}, starting fresh.")
            return []

    def _save_log(self, d: str, entries: List[Dict]):
        with open(self._log_file(d), "w") as f:
            json.dump(entries, f, indent=2)

    def log_workout(self, exercises: List[Dict]) -> Dict[str, Any]:
        """Log workout exercises for today.

        Each exercise dict should contain:
          - exercise_name (str): name matching the exercise catalog
          - sets (int): number of sets performed
          - weight (float, optional): weight used (lbs)
          - max_reps (int, optional): max reps achieved in any set
          - notes (str, optional): free-text notes
        """
        self._ensure_dirs()
        target_date = self.config.get_effective_today().isoformat()
        existing = self._load_log(target_date)

        for entry in exercises:
            if "id" not in entry:
                entry["id"] = uuid.uuid4().hex[:12]

        existing.extend(exercises)
        self._save_log(target_date, existing)

        return {
            "success": True,
            "date": target_date,
            "entries_added": len(exercises),
            "total_entries": len(existing),
        }

    def get_workout_log(self, entry_date: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve the workout log for a date (defaults to today)."""
        if entry_date:
            try:
                datetime.strptime(entry_date, "%Y-%m-%d")
                target_date = entry_date
            except ValueError:
                return {"error": f"Invalid date format: {entry_date}. Use YYYY-MM-DD."}
        else:
            target_date = self.config.get_effective_today().isoformat()

        entries = self._load_log(target_date)
        if not entries:
            return {"date": target_date, "entries": [], "message": "No workout logged for this date."}

        return {"date": target_date, "entries": entries}

    def revise_workout_entry(
        self, entry_id: str, updates: Dict, entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Revise a previously logged workout entry by ID."""
        if entry_date:
            try:
                datetime.strptime(entry_date, "%Y-%m-%d")
                target_date = entry_date
            except ValueError:
                return {"error": f"Invalid date format: {entry_date}. Use YYYY-MM-DD."}
        else:
            target_date = self.config.get_effective_today().isoformat()

        entries = self._load_log(target_date)
        for entry in entries:
            if entry.get("id") == entry_id:
                entry.update(updates)
                self._save_log(target_date, entries)
                return {"success": True, "message": f"Updated entry {entry_id} on {target_date}."}

        return {"error": f"Entry '{entry_id}' not found on {target_date}."}

    def remove_workout_entry(
        self, entry_id: str, entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Remove a workout entry by ID."""
        if entry_date:
            try:
                datetime.strptime(entry_date, "%Y-%m-%d")
                target_date = entry_date
            except ValueError:
                return {"error": f"Invalid date format: {entry_date}. Use YYYY-MM-DD."}
        else:
            target_date = self.config.get_effective_today().isoformat()

        entries = self._load_log(target_date)
        before = len(entries)
        entries = [e for e in entries if e.get("id") != entry_id]
        if len(entries) == before:
            return {"error": f"Entry '{entry_id}' not found on {target_date}."}

        self._save_log(target_date, entries)
        return {"success": True, "message": f"Removed entry {entry_id} from {target_date}."}
