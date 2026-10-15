"""Tests for WorkoutSDK.search_workouts — the one multi-row read: filtered
rows with optional exact period stats — and the catalog/log consistency
helpers behind it."""

import json
import os
import time
from datetime import date, timedelta

import pytest
from unittest.mock import patch
from mcp_app.models import UserRecord
from echofit.context import current_user
from echofit.workout import WorkoutSDK


@pytest.fixture(autouse=True)
def isolated_env(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    with patch.dict(os.environ, {
        "ECHOFIT_DATA": str(data_dir),
        "ECHOFIT_CONFIG": str(config_dir),
    }):
        token = current_user.set(UserRecord(email="test-user"))
        yield data_dir
        current_user.reset(token)


@pytest.fixture
def sdk():
    return WorkoutSDK()


def _seed(sdk):
    """Curls across three months plus unrelated Rows; one curl has no weight."""
    sdk.add_exercise("Curls", "Arms")
    sdk.add_exercise("Rows", "Back")
    sdk.add_exercise("Bench", "Chest")
    j = sdk._journal
    j.append([{"exercise_name": "Curls", "sets": 2, "weight": 50, "max_reps": 10}], "2025-01-05")
    j.append([{"exercise_name": "Rows", "sets": 3, "weight": 90, "max_reps": 12}], "2025-01-05")
    j.append([{"exercise_name": "Curls", "sets": 1, "weight": 60, "max_reps": 6}], "2025-01-20")
    j.append([{"exercise_name": "Curls", "sets": 2, "weight": 60, "max_reps": 8}], "2025-02-10")
    j.append([
        {"exercise_name": "Curls", "sets": 1, "weight": 50, "max_reps": 12},
        {"exercise_name": "Curls", "sets": 1, "weight": 60, "max_reps": 8, "notes": "second set"},
    ], "2025-03-01")
    j.append([{"exercise_name": "curls", "sets": 1, "max_reps": 15}], "2025-03-15")  # bodyweight / band


class TestRows:
    def test_default_is_newest_first_with_est_1rm(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], workouts=2)
        assert [r["date"] for r in res["rows"]] == ["2025-03-15", "2025-03-01", "2025-03-01"]
        assert (res["workouts"], res["newest_date"], res["oldest_date"]) == (2, "2025-03-15", "2025-03-01")
        assert res["rows"][1]["notes"] == "second set"          # newest-logged first within a day
        assert res["rows"][1]["est_1rm"] == 76.0                # 60 × (1 + 8/30)
        assert "est_1rm" not in res["rows"][0]                  # no weight → no score
        assert all("id" in r for r in res["rows"])
        assert res["has_more"] is True and res["count"] == 3
        assert "stats" not in res and "total_rows" not in res

    def test_est_1rm_is_undefined_above_twelve_reps(self, sdk):
        assert WorkoutSDK.est_1rm(60, 12) == 84.0
        assert WorkoutSDK.est_1rm(60, 13) is None
        assert WorkoutSDK.est_1rm(60, 0) is None
        assert WorkoutSDK.est_1rm(None, 8) is None
        assert WorkoutSDK.est_1rm(40, 2) == 42.7

    def test_multi_key_sort_with_mixed_directions(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], workouts=10,
                                  sort=[{"by": "weight", "dir": "asc"}, {"by": "max_reps", "dir": "desc"}])
        got = [(r.get("weight"), r["max_reps"], r["date"]) for r in res["rows"]]
        assert got == [
            (50, 12, "2025-03-01"), (50, 10, "2025-01-05"),
            (60, 8, "2025-03-01"), (60, 8, "2025-02-10"), (60, 6, "2025-01-20"),
            (None, 15, "2025-03-15"),                       # missing weight last even when ascending
        ]
        assert res["sort"] == [{"by": "weight", "dir": "asc"}, {"by": "max_reps", "dir": "desc"}]

    def test_sort_by_est_1rm_finds_the_strongest_set(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], workouts=10, sort=[{"by": "est_1rm"}])
        assert (res["rows"][0]["weight"], res["rows"][0]["max_reps"], res["rows"][0]["est_1rm"]) == (60, 8, 76.0)
        assert "est_1rm" not in res["rows"][-1]                          # unscored rows sort last

    def test_fields_restrict_rows(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], workouts=2, fields=["date", "weight", "max_reps"])
        assert res["rows"] == [
            {"date": "2025-03-15", "max_reps": 15},          # no weight stored → key omitted
            {"date": "2025-03-01", "weight": 60, "max_reps": 8},
            {"date": "2025-03-01", "weight": 50, "max_reps": 12},   # cut landed mid-day → day completed
        ]
        assert res["fields"] == ["date", "weight", "max_reps"]

    def test_no_exercise_filter_returns_everything(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(workouts=100)
        assert res["count"] == 7
        assert res["filters"]["exercises"] is None

    def test_names_resolve_to_catalog_spelling_and_dedupe(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["curls", "CURLS", "rows"], workouts=100)
        assert res["filters"]["exercises"] == ["Curls", "Rows"]
        assert res["count"] == 7


class TestFilters:
    def test_weight_and_reps_bounds_are_inclusive(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], min_weight=60, min_reps=8, workouts=10)
        assert res["count"] == 2                               # 60x8 on 02-10 and 03-01
        res = sdk.search_workouts(exercises=["Curls"], max_weight=50, max_reps=10, workouts=10)
        assert [(r["weight"], r["max_reps"]) for r in res["rows"]] == [(50, 10)]
        res = sdk.search_workouts(exercises=["Curls"], min_weight=60, max_weight=60, workouts=10)
        assert res["count"] == 3

    def test_rows_missing_a_bounded_field_are_excluded(self, sdk):
        _seed(sdk)
        assert sdk.search_workouts(exercises=["Curls"], min_weight=1, workouts=10)["count"] == 5
        assert sdk.search_workouts(exercises=["Curls"], max_weight=999, workouts=10)["count"] == 5
        assert sdk.search_workouts(exercises=["Curls"], min_reps=1, workouts=10)["count"] == 6

    def test_since_until_window_is_inclusive(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], since="2025-01-20", until="2025-02-10")
        assert res["count"] == 2
        assert res["period"] == {"since": "2025-01-20", "until": "2025-02-10"}

    def test_days_resolves_to_since_from_effective_today(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        today = sdk.config.get_effective_today()
        j = sdk._journal
        j.append([{"exercise_name": "Curls", "weight": 60, "max_reps": 8}], (today - timedelta(days=10)).isoformat())
        j.append([{"exercise_name": "Curls", "weight": 60, "max_reps": 9}], (today - timedelta(days=6)).isoformat())
        j.append([{"exercise_name": "Curls", "weight": 60, "max_reps": 10}], today.isoformat())
        res = sdk.search_workouts(exercises=["Curls"], days=7)
        assert res["count"] == 2
        assert res["period"]["since"] == (today - timedelta(days=6)).isoformat()

    def test_open_ended_stats_cover_all_history(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        j = sdk._journal
        j.append([{"exercise_name": "Curls", "weight": 70, "max_reps": 5}], "2022-01-10")  # the true PR, long ago
        for m in range(1, 13):
            j.append([{"exercise_name": "Curls", "weight": 50, "max_reps": 10}], f"2025-{m:02d}-10")
        for m in range(1, 7):
            j.append([{"exercise_name": "Curls", "weight": 55, "max_reps": 10}], f"2026-{m:02d}-10")
        res = sdk.search_workouts(exercises=["Curls"], stats=True, workouts=0)
        assert res["stats"][0]["max_weight"] == 70
        assert res["months_scanned"] == 19
        assert res["scanned_through"] == "2022-01"
        assert res["rows"] == [] and res["has_more"] is True

    @pytest.mark.parametrize("kwargs,fragment", [
        ({"exercises": []}, "non-empty list"),
        ({"exercises": ["Curls", "Hammer Curls"]}, "Unknown exercise(s): 'Hammer Curls'"),
        ({"sort": "weight"}, "sort must be a list"),
        ({"sort": [{"by": "volume"}]}, "sort field 'volume'"),
        ({"sort": [{"by": "weight", "dir": "down"}]}, "must be 'asc' or 'desc'"),
        ({"sort": [{"dir": "asc"}]}, "Each sort item"),
        ({"fields": ["date", "volume"]}, "fields must be"),
        ({"fields": []}, "fields must be"),
        ({"workouts": -1}, "workouts must be"),
        ({"days": 0}, "days must be"),
        ({"days": 7, "since": "2025-01-01"}, "not both"),
        ({"since": "2025-13-01"}, "Invalid since"),
        ({"since": "2025-03-01", "until": "2025-01-01"}, "after until"),
        ({"min_weight": 60, "max_weight": 50}, "min_weight (60) is greater"),
        ({"min_reps": 10, "max_reps": 5}, "min_reps (10) is greater"),
    ])
    def test_invalid_arguments_return_errors(self, sdk, kwargs, fragment):
        _seed(sdk)
        assert fragment in sdk.search_workouts(**kwargs)["error"]


class TestStats:
    def test_stats_cover_every_matching_row_regardless_of_limit(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], stats=True, workouts=1)
        assert res["count"] == 1 and res["has_more"] is True
        assert res["total_rows"] == 6 and res["sessions"] == 5
        s = res["stats"][0]
        assert s["exercise"] == "Curls"
        assert s["total_rows"] == 6                       # case-insensitive, Rows excluded
        assert s["total_sets"] == 8
        assert s["sessions"] == 5
        assert s["first_date"] == "2025-01-05"
        assert s["last_date"] == "2025-03-15"
        assert s["max_weight"] == 60
        assert s["max_reps"] == 15
        assert s["best_est_1rm"] == {"est_1rm": 76.0, "weight": 60, "max_reps": 8, "date": "2025-03-01"}

    def test_by_weight_lists_every_weight_with_sets_and_rep_range(self, sdk):
        _seed(sdk)
        bw = sdk.search_workouts(exercises=["Curls"], stats=True, workouts=0)["stats"][0]["by_weight"]
        assert [b["weight"] for b in bw] == [60, 50, None]
        assert bw[0] == {"weight": 60, "sets": 4, "rows": 3, "min_reps": 6, "max_reps": 8,
                         "first_date": "2025-01-20", "last_date": "2025-03-01"}
        assert bw[1] == {"weight": 50, "sets": 3, "rows": 2, "min_reps": 10, "max_reps": 12,
                         "first_date": "2025-01-05", "last_date": "2025-03-01"}
        assert bw[2] == {"weight": None, "sets": 1, "rows": 1, "min_reps": 15, "max_reps": 15,
                         "first_date": "2025-03-15", "last_date": "2025-03-15"}

    def test_a_weight_tried_once_stays_visible_beside_the_working_weight(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        j = sdk._journal
        j.append([{"exercise_name": "Curls", "sets": 1, "weight": 40, "max_reps": 2}], "2025-01-05")
        for d in range(10, 30):
            j.append([{"exercise_name": "Curls", "sets": 1, "weight": 30, "max_reps": 8 + d // 10}], f"2025-01-{d}")
        s = sdk.search_workouts(exercises=["Curls"], stats=True, workouts=0)["stats"][0]
        assert [(b["weight"], b["sets"], b["min_reps"], b["max_reps"]) for b in s["by_weight"]] == [
            (40, 1, 2, 2), (30, 20, 9, 10),
        ]
        assert s["max_weight"] == 40
        assert s["best_est_1rm"]["weight"] == 40           # 42.7 beats 30x10 = 40.0

    def test_stats_without_exercise_filter_block_per_exercise_found(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(stats=True, workouts=0)
        assert [b["exercise"] for b in res["stats"]] == ["Curls", "Rows"]   # most rows first
        assert res["stats"][1]["max_weight"] == 90
        assert res["total_rows"] == 7

    def test_filters_apply_to_stats_too(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Curls"], min_weight=60, min_reps=8, stats=True)
        assert res["stats"][0]["total_rows"] == 2
        assert res["stats"][0]["max_reps"] == 8
        assert res["filters"]["min_weight"] == 60

    def test_empty_result_has_null_stats_not_errors(self, sdk):
        _seed(sdk)
        res = sdk.search_workouts(exercises=["Bench"], stats=True)
        assert res["stats"][0]["total_rows"] == 0
        assert res["stats"][0]["max_weight"] is None
        assert res["stats"][0]["best_est_1rm"] is None
        assert res["stats"][0]["by_weight"] == []
        assert res["rows"] == [] and res["has_more"] is False


class TestExerciseNameConsistency:
    def test_audit_reports_orphans_and_case_mismatches(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        sdk.add_exercise("Rows", "Back")
        j = sdk._journal
        j.append([{"exercise_name": "Curls", "sets": 1}], "2025-01-05")
        j.append([{"exercise_name": "curls", "sets": 1}], "2025-01-06")
        j.append([{"exercise_name": "Bicep Curl", "sets": 1}, {"exercise_name": "Bicep Curl", "sets": 1}], "2025-02-05")
        j.append([{"exercise_name": "Rows", "sets": 1}], "2025-02-05")
        a = sdk.audit_exercise_names()
        assert a["clean"] is False
        assert a["orphans"] == [{"exercise_name": "Bicep Curl", "entries": 2}]
        assert a["case_mismatches"] == [{"exercise_name": "curls", "catalog_name": "Curls", "entries": 1}]
        assert (a["catalog_count"], a["logged_names"]) == (2, 4)

    def test_rename_merges_orphans_into_a_catalog_exercise(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        j = sdk._journal
        j.append([{"exercise_name": "Bicep Curl", "sets": 1}], "2025-01-05")
        j.append([{"exercise_name": "bicep curl", "sets": 1}], "2025-03-05")
        j.append([{"exercise_name": "Curls", "sets": 1}], "2025-03-06")
        r = sdk.rename_logged_exercise("Bicep Curl", "curls")
        assert (r["entries_changed"], r["shards_changed"]) == (2, 2)
        assert sdk.audit_exercise_names()["clean"] is True
        assert sdk.search_workouts(exercises=["Curls"], stats=True)["total_rows"] == 3
        assert "not in the exercise catalog" in sdk.rename_logged_exercise("Curls", "Hammer Curls")["error"]
        assert sdk.rename_logged_exercise("Nothing Here", "Curls")["entries_changed"] == 0


class TestAtScale:
    """Ten years of daily logging, twelve entries a day, must stay fast and exact."""

    YEARS = 10
    PER_DAY = 12
    EXERCISES = ["Curls", "Rows", "Bench", "Squats", "Press", "Flys"]

    def _seed_decade(self, sdk):
        for name in self.EXERCISES:
            sdk.add_exercise(name)
        j = sdk._journal
        j._ensure_dir()
        start = date(2016, 1, 1)
        shards = {}
        n = 0
        for d in range(self.YEARS * 365):
            day = start + timedelta(days=d)
            rows = []
            for k in range(self.PER_DAY):
                rows.append({
                    "id": f"{d:05d}{k:02d}",
                    "exercise_name": self.EXERCISES[(d + k) % len(self.EXERCISES)],
                    "sets": 1,
                    "weight": 40 + (n % 7) * 5,
                    "max_reps": 5 + (n % 9),
                })
                n += 1
            shards.setdefault(day.strftime("%Y-%m"), {})[day.isoformat()] = rows
        for month, shard in shards.items():
            with open(j._shard_path(month), "w") as f:
                json.dump(shard, f)

    def test_all_time_stats_are_exact_and_fast_on_a_decade(self, sdk):
        self._seed_decade(sdk)
        t0 = time.perf_counter()
        res = sdk.search_workouts(exercises=["Curls"], min_reps=10, stats=True, workouts=5,
                                  sort=[{"by": "weight"}, {"by": "max_reps"}])
        elapsed = time.perf_counter() - t0

        expected = 0
        for d in range(self.YEARS * 365):
            for k in range(self.PER_DAY):
                n = d * self.PER_DAY + k
                if self.EXERCISES[(d + k) % 6] == "Curls" and 5 + (n % 9) >= 10:
                    expected += 1
        assert res["stats"][0]["total_rows"] == expected
        assert res["stats"][0]["max_weight"] == 70
        assert res["months_scanned"] == self.YEARS * 12
        assert res["workouts"] == 5 and res["count"] >= 5
        weights = [r["weight"] for r in res["rows"]]
        assert weights == sorted(weights, reverse=True)                  # page sorted heaviest first
        assert elapsed < 5.0, f"decade scan took {elapsed:.2f}s"

    def test_recent_read_touches_one_month_of_a_decade(self, sdk):
        self._seed_decade(sdk)
        res = sdk.search_workouts(workouts=3)
        assert res["count"] == 36 and res["has_more"] is True   # 12 rows/day → three whole days
        assert res["months_scanned"] == 1
        assert res["scanned_through"] == "2025-12"

    def test_bounded_window_reads_only_its_months(self, sdk):
        self._seed_decade(sdk)
        res = sdk.search_workouts(exercises=["Curls"], since="2020-02-15", until="2020-04-10", stats=True)
        assert res["months_scanned"] == 3
        assert res["stats"][0]["first_date"] >= "2020-02-15"
        assert res["stats"][0]["last_date"] <= "2020-04-10"


class TestWorkoutPaging:
    """The page is the N most recent matching dates, so paging by date
    (until = day before oldest_date) can neither skip nor repeat rows."""

    def _seed_week(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        sdk.add_exercise("Rows", "Back")
        j = sdk._journal
        for d in range(1, 8):  # 7 days × 4 curl rows = 28 rows, plus Rows on odd days
            j.append([{"exercise_name": "Curls", "sets": 1, "weight": 50 + d, "max_reps": k}
                      for k in range(1, 5)], f"2025-03-{d:02d}")
            if d % 2:
                j.append([{"exercise_name": "Rows", "sets": 1, "weight": 90, "max_reps": 10}], f"2025-03-{d:02d}")

    def test_page_is_whole_workouts(self, sdk):
        self._seed_week(sdk)
        res = sdk.search_workouts(workouts=3)
        assert res["workouts"] == 3 and res["count"] == 14         # 03-07(5) 03-06(4) 03-05(5)
        assert (res["newest_date"], res["oldest_date"]) == ("2025-03-07", "2025-03-05")
        assert res["has_more"] is True
        assert res["months_scanned"] == 1

    def test_workouts_count_dates_with_a_matching_row_only(self, sdk):
        self._seed_week(sdk)
        res = sdk.search_workouts(exercises=["Rows"], workouts=2)     # Rows only on 07, 05, 03, 01
        assert [r["date"] for r in res["rows"]] == ["2025-03-07", "2025-03-05"]
        assert res["has_more"] is True
        res = sdk.search_workouts(exercises=["Rows"], workouts=4)
        assert res["workouts"] == 4 and res["has_more"] is False

    def test_zero_workouts_returns_no_rows_but_exact_has_more(self, sdk):
        self._seed_week(sdk)
        res = sdk.search_workouts(workouts=0)
        assert res["count"] == 0 and res["workouts"] == 0 and res["oldest_date"] is None
        assert res["has_more"] is True
        assert sdk.search_workouts(exercises=["Rows"], workouts=0, since="2025-03-08")["has_more"] is False

    def test_walking_back_with_until_reconstructs_everything_once(self, sdk):
        self._seed_week(sdk)
        seen, until, pages = [], None, 0
        while True:
            res = sdk.search_workouts(workouts=3, until=until, fields=["id", "date"])
            pages += 1
            seen.extend(res["rows"])
            if not res["has_more"]:
                break
            until = (date.fromisoformat(res["oldest_date"]) - timedelta(days=1)).isoformat()
        assert pages == 3
        assert len(seen) == 32 and len({r["id"] for r in seen}) == 32

    def test_ascending_sort_orders_the_page_but_the_page_is_still_the_newest(self, sdk):
        self._seed_week(sdk)
        res = sdk.search_workouts(workouts=2, sort=[{"by": "date", "dir": "asc"}], fields=["date"])
        assert [r["date"] for r in res["rows"]][0] == "2025-03-06"
        assert {r["date"] for r in res["rows"]} == {"2025-03-06", "2025-03-07"}
        assert (res["newest_date"], res["oldest_date"]) == ("2025-03-07", "2025-03-06")

    def test_sort_orders_the_page_without_changing_which_workouts(self, sdk):
        self._seed_week(sdk)
        res = sdk.search_workouts(exercises=["Curls"], workouts=2, sort=[{"by": "max_reps"}])
        assert {r["date"] for r in res["rows"]} == {"2025-03-07", "2025-03-06"}
        assert [r["max_reps"] for r in res["rows"]] == [4, 4, 3, 3, 2, 2, 1, 1]
        assert res["rows"][0]["date"] == "2025-03-07"                 # tie → newest first

    def test_stats_see_everything_while_the_page_stays_small(self, sdk):
        self._seed_week(sdk)
        res = sdk.search_workouts(exercises=["Curls"], workouts=1, stats=True)
        assert res["count"] == 4 and res["has_more"] is True
        assert res["total_rows"] == 28 and res["stats"][0]["sessions"] == 7
