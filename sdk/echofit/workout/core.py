import json
import logging
from pathlib import Path
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

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

    def _catalog_name(self, name: Optional[str]) -> Optional[str]:
        """Return the catalog's canonical spelling of ``name`` (case-insensitive), or None."""
        if not name:
            return None
        wanted = name.strip().lower()
        for ex in self._load_exercises():
            if ex["name"].lower() == wanted:
                return ex["name"]
        return None

    def _resolve_exercise_names(self, names: List[str]) -> Tuple[List[str], Optional[Dict]]:
        """Map every name to its catalog spelling; error naming the unknown ones."""
        resolved: List[str] = []
        unknown: List[str] = []
        for n in names:
            canon = self._catalog_name(n)
            if canon is None:
                unknown.append(n)
            elif canon not in resolved:
                resolved.append(canon)
        if unknown:
            return [], {
                "error": "Unknown exercise(s): " + ", ".join(repr(u) for u in unknown)
                + ". Exercise names must match the catalog exactly (case-insensitive). "
                "Call list_exercises to see the catalog, or add_exercise to add a new one.",
                "unknown_exercises": unknown,
            }
        return resolved, None

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
                old_name = ex["name"]
                new_name = updates.get("name")
                if new_name and new_name.lower() != old_name.lower():
                    for other in exercises:
                        if other is not ex and other["name"].lower() == new_name.lower():
                            return {"error": f"Exercise '{new_name}' already exists; "
                                             "use rename_logged_exercise to merge log entries into it."}
                ex.update(updates)
                self._save_exercises(exercises)
                result = {"success": True, "message": f"Updated '{name}'."}
                if new_name and new_name != old_name:
                    # The log stores names, so a rename must follow through
                    # to every entry or history would orphan.
                    renamed = self._journal.rename(old_name, new_name)
                    result["log_entries_renamed"] = renamed.get("entries_changed", 0)
                return result
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

        Every ``exercise_name`` must exist in the exercise catalog
        (case-insensitive); it is stored with the catalog's spelling so the
        log and catalog never drift. Unknown names are rejected before
        anything is written.

        Returns the resolved ``date``, ``entries_added``, the new
        ``total_entries`` for that date, and the assigned ``ids``.
        """
        names = [e.get("exercise_name") or "" for e in exercises]
        _, err = self._resolve_exercise_names(names)
        if err:
            return err
        for e in exercises:
            e["exercise_name"] = self._catalog_name(e["exercise_name"])
        return self._journal.append(exercises)

    # ── search (the one multi-row read) ─────────────────────────

    ROW_FIELDS = ("id", "date", "exercise_name", "sets", "weight", "max_reps", "est_1rm", "notes")
    SORT_FIELDS = ("date", "weight", "max_reps", "sets", "exercise_name", "est_1rm")
    DEFAULT_SORT = [{"by": "date", "dir": "desc"}]
    DEFAULT_WORKOUTS = 5
    EST_1RM_MAX_REPS = 12

    @classmethod
    def est_1rm(cls, weight: Optional[float], reps: Optional[int]) -> Optional[float]:
        """Epley estimated one-rep max: weight × (1 + reps/30).

        A score for comparing sets of the *same* exercise across different
        weight/rep combinations. None when either value is missing or reps
        exceed ``EST_1RM_MAX_REPS`` (the formula is unreliable there).
        """
        if weight is None or reps is None or reps <= 0 or reps > cls.EST_1RM_MAX_REPS:
            return None
        return round(weight * (1 + reps / 30), 1)

    def search_workouts(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        days: Optional[int] = None,
        exercises: Optional[List[str]] = None,
        min_weight: Optional[float] = None,
        max_weight: Optional[float] = None,
        min_reps: Optional[int] = None,
        max_reps: Optional[int] = None,
        workouts: int = DEFAULT_WORKOUTS,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[List[str]] = None,
        stats: bool = False,
    ) -> Dict[str, Any]:
        """Search the workout log: the most recent matching workouts' rows,
        optionally with exact period stats.

        This is the single multi-row read. A **workout** is all the sets
        logged on one calendar day; with filters, a day with at least one
        matching row. The page is every matching row from the ``workouts``
        most recent such days, ordered by ``sort`` — so "my last 10 curls"
        is ``exercises=["Curls"], workouts=10`` — and a page never splits
        a day. Paging is backward only (``until`` = day before the oldest
        date returned): the page is always the most recent workouts, and
        ``sort`` only orders the rows within it. With ``stats=True`` the whole range is
        read once and per-exercise aggregates are computed over **every**
        matching row, regardless of ``workouts`` (``workouts=0`` with
        ``stats=True`` is a pure aggregate call). Without stats, the scan
        stops as soon as it has the page, so "recent" reads touch only the
        latest month file(s).

        Args:
            since / until: inclusive YYYY-MM-DD bounds. Today's workout is
                ``since=until=<today>``. With neither (and no ``days``),
                the whole history is in range.
            days: the last N calendar days up to the effective today; a
                shortcut for ``since``. Cannot be combined with ``since``.
            exercises: optional list of catalog exercise names
                (case-insensitive). Unknown names are an error.
            min_weight / max_weight / min_reps / max_reps: inclusive
                bounds; a row with no value for a bounded field is dropped.
            workouts: how many most-recent matching dates to return rows
                for. Page back with ``until`` = the day before the oldest
                date returned.
            sort: list of ``{"by": <field>, "dir": "asc"|"desc"}`` applied
                in order to the rows of the page (``dir`` defaults to
                ``desc``); fields are ``SORT_FIELDS``. Missing values sort
                last. Ties fall back to newest first.
            fields: which of ``ROW_FIELDS`` to include per row (default all).
            stats: compute per-exercise aggregates over the full range.
        """
        if isinstance(exercises, str):
            exercises = [exercises]
        names: Optional[List[str]] = None
        if exercises is not None:
            if not exercises or not all(isinstance(n, str) and n.strip() for n in exercises):
                return {"error": "exercises must be a non-empty list of exercise names, or omitted."}
            names, err = self._resolve_exercise_names(exercises)
            if err:
                return err
        if workouts < 0:
            return {"error": "workouts must be non-negative."}
        for label, lo, hi in (("weight", min_weight, max_weight), ("reps", min_reps, max_reps)):
            if lo is not None and hi is not None and lo > hi:
                return {"error": f"min_{label} ({lo}) is greater than max_{label} ({hi})."}
        if days is not None:
            if since is not None:
                return {"error": "Pass either days or since, not both."}
            if days <= 0:
                return {"error": "days must be positive."}
            today = self.config.get_effective_today()
            since = (today - timedelta(days=days - 1)).isoformat()

        sort_keys, err = self._parse_sort(sort)
        if err:
            return err
        if fields is None:
            fields = list(self.ROW_FIELDS)
        else:
            bad = [f for f in fields if f not in self.ROW_FIELDS]
            if bad or not fields:
                return {"error": f"fields must be a non-empty subset of {', '.join(self.ROW_FIELDS)}; "
                                 f"got {bad or fields}."}

        wanted = {n.lower() for n in names} if names else None

        def _match(entry: Dict) -> bool:
            if wanted is not None and (entry.get("exercise_name") or "").lower() not in wanted:
                return False
            w, r = entry.get("weight"), entry.get("max_reps")
            if min_weight is not None and (w is None or w < min_weight):
                return False
            if max_weight is not None and (w is None or w > max_weight):
                return False
            if min_reps is not None and (r is None or r < min_reps):
                return False
            if max_reps is not None and (r is None or r > max_reps):
                return False
            return True

        # The page is chosen by recency alone, so without aggregates the
        # scan can stop once it has the page (plus one older row for has_more).
        scan = self._journal.scan(
            since=since, until=until, match=_match,
            stop_after_dates=None if stats else workouts,
        )
        if "error" in scan:
            return scan
        rows: List[Dict] = scan["entries"]  # newest first
        for e in rows:
            e["est_1rm"] = self.est_1rm(e.get("weight"), e.get("max_reps"))

        page_dates: List[str] = []
        for e in rows:
            if e["date"] not in page_dates:
                if len(page_dates) == workouts:
                    break
                page_dates.append(e["date"])
        page = [e for e in rows if e["date"] in page_dates]
        has_more = len(rows) > len(page)
        page = self._apply_sort(page, sort_keys)
        page = [{f: e.get(f) for f in fields if e.get(f) is not None or f in e and f != "est_1rm"} for e in page]

        result: Dict[str, Any] = {
            "period": {"since": since, "until": until},
            "filters": {
                "exercises": names, "min_weight": min_weight, "max_weight": max_weight,
                "min_reps": min_reps, "max_reps": max_reps,
            },
            "rows": page,
            "count": len(page),
            "workouts": len(page_dates),
            "newest_date": page_dates[0] if page_dates else None,
            "oldest_date": page_dates[-1] if page_dates else None,
            "has_more": has_more,
            "sort": sort_keys,
            "fields": fields,
            "months_scanned": scan["months_scanned"],
            "scanned_through": scan["scanned_through"],
        }
        if stats:
            result["total_rows"] = len(rows)
            result["sessions"] = len({e["date"] for e in rows})
            if names:
                order = names
            else:  # every exercise found, grouped case-insensitively, most rows first
                counts: Dict[str, int] = {}
                label: Dict[str, str] = {}
                for e in rows:
                    stored = e.get("exercise_name") or ""
                    key = stored.lower()
                    counts[key] = counts.get(key, 0) + 1
                    label.setdefault(key, self._catalog_name(stored) or stored)
                order = [label[k] for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
            result["stats"] = [
                {"exercise": name, **self._period_stats(
                    [e for e in rows if (e.get("exercise_name") or "").lower() == name.lower()]
                )}
                for name in order
            ]
        return result

    def _parse_sort(self, sort: Optional[List[Dict[str, str]]]) -> Tuple[List[Dict[str, str]], Optional[Dict]]:
        if sort is None or sort == []:
            return list(self.DEFAULT_SORT), None
        if not isinstance(sort, list):
            return [], {"error": 'sort must be a list like [{"by": "weight", "dir": "desc"}].'}
        keys: List[Dict[str, str]] = []
        for item in sort:
            if not isinstance(item, dict) or "by" not in item:
                return [], {"error": 'Each sort item must be {"by": <field>, "dir": "asc"|"desc"}.'}
            by = item["by"]
            direction = item.get("dir", "desc")
            if by not in self.SORT_FIELDS:
                return [], {"error": f"sort field {by!r} is not one of {', '.join(self.SORT_FIELDS)}."}
            if direction not in ("asc", "desc"):
                return [], {"error": f"sort dir for {by!r} must be 'asc' or 'desc', got {direction!r}."}
            keys.append({"by": by, "dir": direction})
        return keys, None

    @staticmethod
    def _apply_sort(rows: List[Dict], keys: List[Dict[str, str]]) -> List[Dict]:
        """Stable multi-key sort; rows arrive newest-first, which is the final tiebreak.
        Missing values always sort last whatever the direction."""
        out = list(rows)
        for key in reversed(keys):  # least significant first; each pass is stable
            field, desc = key["by"], key["dir"] == "desc"
            present = [e for e in out if e.get(field) is not None]
            missing = [e for e in out if e.get(field) is None]
            present.sort(key=lambda e: e[field], reverse=desc)
            out = present + missing
        return out

    @classmethod
    def _period_stats(cls, rows: List[Dict]) -> Dict[str, Any]:
        """Exact aggregates over every matched row of one exercise (newest first)."""
        if not rows:
            return {
                "total_rows": 0, "total_sets": 0, "sessions": 0,
                "first_date": None, "last_date": None,
                "max_weight": None, "max_reps": None, "best_est_1rm": None, "by_weight": [],
            }

        weighted = [e for e in rows if e.get("weight") is not None]
        repped = [e for e in rows if e.get("max_reps") is not None]

        best = None
        for e in rows:  # newest first → the most recent best wins ties
            score = cls.est_1rm(e.get("weight"), e.get("max_reps"))
            if score is not None and (best is None or score > best["est_1rm"]):
                best = {"est_1rm": score, "weight": e["weight"], "max_reps": e["max_reps"], "date": e["date"]}

        by_weight: Dict[Any, Dict[str, Any]] = {}
        for e in rows:  # newest first → first seen is last_date
            w = e.get("weight")
            b = by_weight.setdefault(w, {
                "weight": w, "sets": 0, "rows": 0, "min_reps": None, "max_reps": None,
                "first_date": e["date"], "last_date": e["date"],
            })
            b["rows"] += 1
            b["sets"] += int(e.get("sets") or 0)
            b["first_date"] = e["date"]  # keeps descending → ends on oldest
            r = e.get("max_reps")
            if r is not None:
                b["min_reps"] = r if b["min_reps"] is None else min(b["min_reps"], r)
                b["max_reps"] = r if b["max_reps"] is None else max(b["max_reps"], r)
        by_weight_list = sorted(
            by_weight.values(),
            key=lambda b: (b["weight"] is None, -(b["weight"] or 0)),
        )

        return {
            "total_rows": len(rows),
            "total_sets": sum(int(e.get("sets") or 0) for e in rows),
            "sessions": len({e["date"] for e in rows}),
            "first_date": rows[-1]["date"],
            "last_date": rows[0]["date"],
            "max_weight": max((e["weight"] for e in weighted), default=None),
            "max_reps": max((e["max_reps"] for e in repped), default=None),
            "best_est_1rm": best,
            "by_weight": by_weight_list,
        }

    # ── catalog / log consistency ───────────────────────────────

    def audit_exercise_names(self) -> Dict[str, Any]:
        """Compare every exercise name in the log against the catalog.

        Reads all history once. Reports names logged under a spelling that
        is not in the catalog (``orphans``, with entry counts) and names
        whose stored spelling differs only in case from the catalog's
        (``case_mismatches``). Both are fixed with
        :meth:`rename_logged_exercise`.
        """
        catalog = {ex["name"].lower(): ex["name"] for ex in self._load_exercises()}
        counts = self._journal.count_names()
        orphans = []
        case_mismatches = []
        for stored, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            canon = catalog.get(stored.lower())
            if canon is None:
                orphans.append({"exercise_name": stored, "entries": n})
            elif canon != stored:
                case_mismatches.append({"exercise_name": stored, "catalog_name": canon, "entries": n})
        return {
            "catalog_count": len(catalog),
            "logged_names": len(counts),
            "orphans": orphans,
            "case_mismatches": case_mismatches,
            "clean": not orphans and not case_mismatches,
        }

    def rename_logged_exercise(self, old_name: str, new_name: str) -> Dict[str, Any]:
        """Rewrite every log entry named ``old_name`` to the catalog exercise
        ``new_name``. ``new_name`` must exist in the catalog (stored with its
        exact spelling); ``old_name`` need not — this is how orphaned
        spellings are merged into a catalog exercise."""
        canon = self._catalog_name(new_name)
        if canon is None:
            return {"error": f"'{new_name}' is not in the exercise catalog. Add it first with add_exercise, "
                             "or rename the catalog entry with update_exercise."}
        if not old_name or not old_name.strip():
            return {"error": "old_name is required."}
        return self._journal.rename(old_name, canon)

    def migrate_storage(self) -> Dict[str, Any]:
        """One-time fold of legacy per-date files into month shards.

        Idempotent — safe to call repeatedly; a no-op once migration is done.
        """
        return self._journal.migrate_legacy_day_files()

    def revise_workout_entry(
        self, entry_id: str, updates: Dict, entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Revise a previously logged workout entry by ID (defaults to today).
        A new ``exercise_name`` must exist in the catalog and is stored with
        the catalog's spelling."""
        if "exercise_name" in updates:
            _, err = self._resolve_exercise_names([updates.get("exercise_name") or ""])
            if err:
                return err
            updates = {**updates, "exercise_name": self._catalog_name(updates["exercise_name"])}
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
