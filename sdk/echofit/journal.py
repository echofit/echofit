"""DailyJournal — month-sharded, cursor-read entry storage for echofit modules.

A journal stores dated entries grouped one object per **month**:

    workouts/2026-06.json   ->   { "2026-06-17": [ {entry}, ... ],
                                   "2026-06-19": [ {entry}, ... ] }

Why month shards: on an object store (Cloud Run + gcsfuse) every read is a
per-object round-trip and a directory listing scales with the number of
objects. One file per day makes "recent / range / trend" queries list and
read O(days). One file per month bounds that to ~12 objects/year — a tiny
listing plus a couple of reads.

Reads are a **clock-free reverse scan** (:meth:`DailyJournal.scan`). The
most recent data is *discovered* by listing shard names and taking the
largest (shard names are sortable ``YYYY-MM`` keys) — never by computing
"today", which may be empty. The scan walks backward shard-by-shard,
reading each in-range shard once and filtering rows in memory. A caller
that only needs the newest N rows passes ``stop_after`` so the walk ends as
soon as it has them; a caller computing aggregates reads the whole range,
and an explicit ``since``/``until`` bounds the files touched.

Invariants:

* **Adds are append-only.** The only full-shard writer (:meth:`_write_shard`)
  is private; callers reach it through :meth:`append`, which extends a day.
* **Edits/removes/moves address entries by ``id``** — never by index.
* **Every read and mutation echoes server-derived facts the caller did not
  supply:** the resolved ``date`` and the authoritative ``total_entries``.

The journal always writes inside its own ``subdir``; the per-user root is
reserved for the framework's identity record (``user.json``).
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:  # tie the reserved-root guard to the framework's actual key
    from mcp_app.bridge import DataStoreAuthAdapter

    FRAMEWORK_RESERVED_ROOT_KEY = DataStoreAuthAdapter.USER_KEY
except Exception:  # pragma: no cover
    FRAMEWORK_RESERVED_ROOT_KEY = "user"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class DailyJournal:
    """One module's dated entry log, scoped to the current user.

    Args:
        config: an ``EchoFitConfig`` (supplies ``data_dir`` and effective-today).
        subdir: namespace subdirectory under the per-user data dir (e.g.
            ``"workouts"``). Must be non-empty and not the reserved root key.
        name_field: entry field used to filter/summarize by name
            (e.g. ``"exercise_name"``).
        legacy_suffix: per-date filename suffix of the pre-shard layout
            (e.g. ``"_workout.json"``), used only by the one-time migration.
    """

    def __init__(
        self,
        config,
        subdir: str,
        name_field: Optional[str] = None,
        legacy_suffix: Optional[str] = None,
    ):
        if not subdir or subdir == FRAMEWORK_RESERVED_ROOT_KEY:
            raise ValueError(
                f"DailyJournal subdir must be a non-empty namespace other than "
                f"the framework-reserved root key "
                f"'{FRAMEWORK_RESERVED_ROOT_KEY}'; got {subdir!r}."
            )
        self.config = config
        self.subdir = subdir
        self.name_field = name_field
        self.legacy_suffix = legacy_suffix

    # ── paths ───────────────────────────────────────────────────

    @property
    def dir(self) -> Path:
        return self.config.data_dir / self.subdir

    def _shard_path(self, month: str) -> Path:
        return self.dir / f"{month}.json"

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    # ── date helpers ────────────────────────────────────────────

    def today(self) -> str:
        return self.config.get_effective_today().isoformat()

    @staticmethod
    def _month_of(date_str: str) -> str:
        return date_str[:7]

    @staticmethod
    def _valid_date(date_str: str) -> bool:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except (ValueError, TypeError):
            return False

    def _resolve_date(self, entry_date: Optional[str]) -> Tuple[Optional[str], Optional[Dict]]:
        if entry_date is None:
            return self.today(), None
        if not self._valid_date(entry_date):
            return None, {"error": f"Invalid date format: {entry_date}. Use YYYY-MM-DD."}
        return entry_date, None

    # ── shard load / write ──────────────────────────────────────

    def load_shard(self, month: str) -> Dict[str, List[Dict]]:
        """Load a month shard as {date: [entries]} (empty dict if absent)."""
        path = self._shard_path(month)
        if not path.exists():
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            logger.warning(f"Bad JSON in {path}, treating as empty.")
            return {}

    def _write_shard(self, month: str, shard: Dict[str, List[Dict]]) -> None:
        """Replace a whole month shard. PRIVATE — never expose publicly.

        Drops empty days and deletes the file when the month becomes empty,
        so shard enumeration stays accurate.
        """
        shard = {d: e for d, e in shard.items() if e}
        path = self._shard_path(month)
        if shard:
            self._ensure_dir()
            with open(path, "w") as f:
                json.dump(shard, f, indent=2, sort_keys=True)
        elif path.exists():
            path.unlink()

    def load_day(self, date_str: str) -> List[Dict]:
        return self.load_shard(self._month_of(date_str)).get(date_str, [])

    # ── enumeration ─────────────────────────────────────────────

    def list_shards(self) -> List[str]:
        """All month keys that have a shard, ascending (YYYY-MM sorts lexically)."""
        if not self.dir.exists():
            return []
        months = []
        for path in self.dir.glob("*.json"):
            month = path.stem
            try:
                datetime.strptime(month, "%Y-%m")
                months.append(month)
            except ValueError:
                continue
        return sorted(months)

    # ── write operations ────────────────────────────────────────

    def append(
        self, entries: List[Dict], entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Append entries to a date (defaults to today). Append-only."""
        date_str, err = self._resolve_date(entry_date)
        if err:
            return err

        ids = []
        for entry in entries:
            if "id" not in entry:
                entry["id"] = _new_id()
            ids.append(entry["id"])

        month = self._month_of(date_str)
        shard = self.load_shard(month)
        day = shard.setdefault(date_str, [])
        day.extend(entries)
        self._write_shard(month, shard)

        return {
            "success": True,
            "date": date_str,
            "entries_added": len(entries),
            "total_entries": len(day),
            "ids": ids,
        }

    def revise(
        self, entry_id: str, updates: Dict, entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update one entry by ``id`` (defaults to today's date)."""
        date_str, err = self._resolve_date(entry_date)
        if err:
            return err

        month = self._month_of(date_str)
        shard = self.load_shard(month)
        day = shard.get(date_str, [])
        for entry in day:
            if entry.get("id") == entry_id:
                entry.update(updates)
                entry["id"] = entry_id  # identity is immutable
                self._write_shard(month, shard)
                return {
                    "success": True,
                    "date": date_str,
                    "entry_id": entry_id,
                    "total_entries": len(day),
                }
        return {"error": f"Entry '{entry_id}' not found on {date_str}."}

    def remove(
        self, entry_id: str, entry_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Remove one entry by ``id`` (defaults to today's date)."""
        date_str, err = self._resolve_date(entry_date)
        if err:
            return err

        month = self._month_of(date_str)
        shard = self.load_shard(month)
        day = shard.get(date_str, [])
        remaining = [e for e in day if e.get("id") != entry_id]
        if len(remaining) == len(day):
            return {"error": f"Entry '{entry_id}' not found on {date_str}."}

        shard[date_str] = remaining
        self._write_shard(month, shard)
        return {
            "success": True,
            "date": date_str,
            "removed_id": entry_id,
            "total_entries": len(remaining),
        }

    def move(
        self, entry_ids: List[str], source_date: str, target_date: str
    ) -> Dict[str, Any]:
        """Move entries by ``id`` from one date to another (target-first)."""
        for d in (source_date, target_date):
            if not self._valid_date(d):
                return {"error": f"Invalid date format: {d}. Use YYYY-MM-DD."}
        if source_date == target_date:
            return {"error": "Source and target dates must be different."}

        sm, tm = self._month_of(source_date), self._month_of(target_date)
        src_shard = self.load_shard(sm)
        src_day = src_shard.get(source_date, [])
        if not src_day:
            return {"error": f"No entries found for {source_date}."}

        wanted = set(entry_ids)
        to_move = [e for e in src_day if e.get("id") in wanted]
        remaining = [e for e in src_day if e.get("id") not in wanted]
        missing = wanted - {e.get("id") for e in to_move}
        if missing:
            return {
                "error": f"Entry IDs not found on {source_date}: {', '.join(sorted(missing))}"
            }

        if tm == sm:
            tgt_day = src_shard.get(target_date, []) + to_move
            src_shard[target_date] = tgt_day
            src_shard[source_date] = remaining
            self._write_shard(sm, src_shard)
        else:
            tgt_shard = self.load_shard(tm)
            tgt_day = tgt_shard.get(target_date, []) + to_move
            tgt_shard[target_date] = tgt_day
            self._write_shard(tm, tgt_shard)  # target first
            src_shard[source_date] = remaining
            self._write_shard(sm, src_shard)  # then prune source

        result = {
            "success": True,
            "moved": len(to_move),
            "moved_ids": [e.get("id") for e in to_move],
            "source_date": source_date,
            "target_date": target_date,
            "source_total_entries": len(remaining),
            "target_total_entries": len(tgt_day),
        }
        if self.name_field:
            result["moved_entries"] = [e.get(self.name_field, "unknown") for e in to_move]
        return result

    # ── name maintenance ────────────────────────────────────────

    def count_names(self) -> Dict[str, int]:
        """Count entries per distinct ``name_field`` value across all history.

        Keys are the stored spellings (case preserved); reads every shard once.
        """
        counts: Dict[str, int] = {}
        if not self.name_field:
            return counts
        for month in self.list_shards():
            for day in self.load_shard(month).values():
                for entry in day:
                    name = entry.get(self.name_field)
                    if name:
                        counts[name] = counts.get(name, 0) + 1
        return counts

    def rename(self, old_name: str, new_name: str) -> Dict[str, Any]:
        """Rewrite ``name_field`` from ``old_name`` (case-insensitive) to
        ``new_name`` on every entry in history. Only shards that contain a
        match are rewritten. Returns the number of entries and shards changed.
        """
        if not self.name_field:
            return {"error": "This journal has no name field."}
        if not old_name or not new_name:
            return {"error": "Both old_name and new_name are required."}
        old_l = old_name.lower()
        entries_changed = 0
        shards_changed = 0
        for month in self.list_shards():
            shard = self.load_shard(month)
            touched = False
            for day in shard.values():
                for entry in day:
                    if (entry.get(self.name_field) or "").lower() == old_l \
                            and entry.get(self.name_field) != new_name:
                        entry[self.name_field] = new_name
                        entries_changed += 1
                        touched = True
            if touched:
                self._write_shard(month, shard)
                shards_changed += 1
        return {
            "success": True,
            "old_name": old_name,
            "new_name": new_name,
            "entries_changed": entries_changed,
            "shards_changed": shards_changed,
        }

    # ── reverse cursor (the read primitive) ─────────────────────

    def _select_months(
        self,
        since: Optional[str],
        until: Optional[str],
        max_active_months: Optional[int],
    ) -> Tuple[List[str], bool]:
        """Return (months_to_scan_desc, more_existed_beyond_budget).

        Explicit since/until define a range and are NOT capped by the
        active-month budget; the budget only bounds open-ended walks.
        """
        months = sorted(self.list_shards(), reverse=True)
        if since:
            months = [m for m in months if m >= self._month_of(since)]
        if until:
            months = [m for m in months if m <= self._month_of(until)]

        more_beyond = False
        explicit_range = since is not None or until is not None
        if (
            not explicit_range
            and max_active_months
            and max_active_months > 0
            and len(months) > max_active_months
        ):
            more_beyond = True
            months = months[:max_active_months]
        return months, more_beyond

    def _matches(self, entry: Dict, name: Optional[str]) -> bool:
        if name is None:
            return True
        if not self.name_field:
            return False
        return (entry.get(self.name_field) or "").lower() == name.lower()

    def scan(
        self,
        name: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        match: Optional[Callable[[Dict], bool]] = None,
        stop_after_dates: Optional[int] = None,
        max_active_months: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Collect matching entries in a range, newest first.

        Each month shard in range is read at most once, newest first; rows
        are filtered in memory by ``name`` and the optional ``match``
        predicate, and every returned entry carries its ``date``.

        ``stop_after_dates`` ends the walk once rows from that many
        distinct dates (the newest ones, since the walk is descending)
        have been collected **and** one row from an older date has been
        seen, so the caller can tell whether more exist. ``0`` stops at the
        first row. Without it every shard in range is read, which is what
        period aggregates need. ``max_active_months``
        defaults to ``None`` (no budget) so an open-ended scan covers all
        history; a budget makes ``scan_truncated`` report skipped months.
        """
        for label, d in (("since", since), ("until", until)):
            if d is not None and not self._valid_date(d):
                return {"error": f"Invalid {label} date: {d}. Use YYYY-MM-DD."}
        if since and until and since > until:
            return {"error": f"since ({since}) is after until ({until})."}

        months, more_beyond = self._select_months(since, until, max_active_months)
        entries: List[Dict] = []
        dates_seen: List[str] = []
        oldest_examined: Optional[str] = None
        months_scanned = 0
        done = False
        for month in months:  # already descending
            months_scanned += 1
            oldest_examined = month
            shard = self.load_shard(month)
            for date_str in sorted(shard.keys(), reverse=True):
                if since and date_str < since:
                    continue
                if until and date_str > until:
                    continue
                for entry in reversed(shard[date_str]):  # newest-logged first
                    if not self._matches(entry, name):
                        continue
                    if match is not None and not match(entry):
                        continue
                    if not dates_seen or dates_seen[-1] != date_str:
                        dates_seen.append(date_str)
                        if stop_after_dates is not None and len(dates_seen) > stop_after_dates:
                            entries.append({**entry, "date": date_str})  # one row past the page
                            done = True
                            break
                    entries.append({**entry, "date": date_str})
                if done:
                    break
            if done:
                break
        return {
            "entries": entries,
            "months_scanned": months_scanned,
            "scanned_through": oldest_examined,
            "scan_truncated": more_beyond,
        }

    # ── one-time migration ──────────────────────────────────────

    def migrate_legacy_day_files(self) -> Dict[str, Any]:
        """Fold pre-shard per-date files into month shards, then delete them.

        Reads each ``{date}{legacy_suffix}`` file (a bare entry array), merges
        its entries into the matching ``{month}.json`` shard under the date
        key, and deletes the legacy file. Idempotent: processed files are
        removed, so re-running is a no-op once migration is complete.
        """
        if not self.legacy_suffix or not self.dir.exists():
            return {"migrated_files": 0, "migrated_entries": 0}

        files = 0
        entries_count = 0
        for path in sorted(self.dir.glob(f"*{self.legacy_suffix}")):
            date_str = path.name[: -len(self.legacy_suffix)]
            if not self._valid_date(date_str):
                continue
            try:
                with open(path, "r") as f:
                    legacy = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(legacy, list):
                continue

            month = self._month_of(date_str)
            shard = self.load_shard(month)
            shard.setdefault(date_str, []).extend(legacy)
            self._write_shard(month, shard)
            path.unlink()
            files += 1
            entries_count += len(legacy)

        return {"migrated_files": files, "migrated_entries": entries_count}
