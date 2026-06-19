"""DailyJournal — month-sharded, cursor-read entry storage for echofit modules.

A journal stores dated entries grouped one object per **month**:

    workouts/2026-06.json   ->   { "2026-06-17": [ {entry}, ... ],
                                   "2026-06-19": [ {entry}, ... ] }

Why month shards: on an object store (Cloud Run + gcsfuse) every read is a
per-object round-trip and a directory listing scales with the number of
objects. One file per day makes "recent / range / trend" queries list and
read O(days). One file per month bounds that to ~12 objects/year — a tiny
listing plus a couple of reads.

Reads are a **clock-free reverse cursor**. The most recent data is
*discovered* by listing shard names and taking the largest (shard names are
sortable ``YYYY-MM`` keys) — never by computing "today", which may be empty.
The cursor walks backward shard-by-shard, lazily reading, stopping as soon
as the request is satisfied. A ``max_active_months`` budget caps worst-case
I/O for queries that can't be satisfied (e.g. "last 5 of an exercise you've
only done 3 times"), so they don't scan all of history.

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
from typing import Any, Dict, List, Optional, Tuple

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

    def query(
        self,
        limit: int = 5,
        unit: str = "sessions",
        name: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        max_active_months: int = 12,
    ) -> Dict[str, Any]:
        """Reverse-chronological cursor read.

        unit="sessions": the ``limit`` most recent dates with data (each with
        its entries, filtered by ``name`` when given), most recent first.
        unit="entries": the ``limit`` most recent individual entries
        (filtered by ``name``), most recent first, each carrying its ``date``.

        ``since``/``until`` (inclusive YYYY-MM-DD) bound the range explicitly.
        ``max_active_months`` caps how many most-recent months-with-data are
        scanned for open-ended (no since/until) walks, bounding worst-case I/O.
        """
        if unit not in ("sessions", "entries"):
            return {"error": "unit must be 'sessions' or 'entries'."}
        for label, d in (("since", since), ("until", until)):
            if d is not None and not self._valid_date(d):
                return {"error": f"Invalid {label} date: {d}. Use YYYY-MM-DD."}
        if limit < 0:
            return {"error": "limit must be non-negative."}

        months, more_beyond = self._select_months(since, until, max_active_months)

        # Collect one past the limit so "has_more" is exact even when the
        # limit lands on a shard boundary, then trim back to limit.
        cap = limit + 1
        collected: List[Dict] = []  # sessions or flat entries depending on unit
        oldest_examined: Optional[str] = None
        months_scanned = 0

        def _full() -> bool:
            return len(collected) >= cap

        for month in months:  # already descending
            months_scanned += 1
            oldest_examined = month
            shard = self.load_shard(month)
            for date_str in sorted(shard.keys(), reverse=True):
                if since and date_str < since:
                    continue
                if until and date_str > until:
                    continue
                day_entries = shard[date_str]
                matched = [e for e in day_entries if self._matches(e, name)]
                if not matched:
                    continue

                if unit == "sessions":
                    collected.append(
                        {
                            "date": date_str,
                            "entries": matched,
                            "total_entries": len(day_entries),
                        }
                    )
                    if _full():
                        break
                else:  # entries — newest within a day first
                    for entry in reversed(matched):
                        collected.append({**entry, "date": date_str})
                        if _full():
                            break
                    if _full():
                        break
            if _full():
                break

        has_more = len(collected) > limit
        results = collected[:limit]
        satisfied = len(results) >= limit
        # Truncated only if the budget cut off months we never read AND we
        # still couldn't satisfy the request within the budget.
        scan_truncated = more_beyond and not satisfied

        result: Dict[str, Any] = {
            "count": len(results),
            "has_more": has_more,
            "months_scanned": months_scanned,
            "scanned_through": oldest_examined,
            "scan_truncated": scan_truncated,
        }
        result["sessions" if unit == "sessions" else "entries"] = results
        return result

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
