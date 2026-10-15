"""Tests for WorkoutSDK — exercise catalog and workout logging."""

import os
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


# ── exercise catalog ────────────────────────────────────────


class TestExerciseCatalog:
    def test_add_exercise(self, sdk):
        result = sdk.add_exercise("Bench Press", "Chest")
        assert result["success"]
        catalog = sdk.list_exercises()
        assert catalog["count"] == 1
        assert catalog["exercises"][0]["name"] == "Bench Press"

    def test_add_duplicate_exercise_rejected(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        result = sdk.add_exercise("curls", "Arms")
        assert "error" in result

    def test_list_exercises_empty(self, sdk):
        result = sdk.list_exercises()
        assert result["count"] == 0
        assert result["exercises"] == []

    def test_list_exercises_filtered_by_target(self, sdk):
        sdk.add_exercise("Bench Press", "Chest")
        sdk.add_exercise("Curls", "Arms")
        sdk.add_exercise("Push-ups", "Chest")
        result = sdk.list_exercises(target="Chest")
        assert result["count"] == 2

    def test_list_exercises_includes_stats_from_logs(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        sdk.log_workout([
            {"exercise_name": "Curls", "sets": 2, "weight": 30, "max_reps": 8},
        ])
        result = sdk.list_exercises()
        ex = result["exercises"][0]
        assert ex["last_performed"] is not None
        assert ex["last_weight"] == 30
        assert ex["last_reps"] == 8
        assert ex["max_weight"] == 30
        assert ex["max_reps"] == 8

    def test_list_exercises_sorted_most_recent_first(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        sdk.add_exercise("Rows", "Back")
        # Only log Curls — it should sort before Rows (which has no log)
        sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])
        result = sdk.list_exercises()
        assert result["exercises"][0]["name"] == "Curls"
        assert result["exercises"][1]["last_performed"] is None

    def test_update_exercise(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        result = sdk.update_exercise("Curls", {"targets": "Biceps"})
        assert result["success"]
        catalog = sdk.list_exercises()
        assert catalog["exercises"][0]["targets"] == "Biceps"

    def test_update_nonexistent_exercise(self, sdk):
        result = sdk.update_exercise("Nope", {"targets": "Legs"})
        assert "error" in result

    def test_remove_exercise(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        result = sdk.remove_exercise("Curls")
        assert result["success"]
        assert sdk.list_exercises()["count"] == 0

    def test_remove_nonexistent_exercise(self, sdk):
        result = sdk.remove_exercise("Nope")
        assert "error" in result


# ── workout logging ─────────────────────────────────────────


def _day(sdk, date):
    """Entries stored on a specific date (test helper, reads the shard)."""
    return sdk._journal.load_day(date)


class TestWorkoutLogging:
    @pytest.fixture(autouse=True)
    def _catalog(self, sdk):
        for name, target in (("Bench Press", "Chest"), ("Curls", "Arms"), ("Rows", "Back")):
            sdk.add_exercise(name, target)

    def test_log_unknown_exercise_is_rejected_before_writing(self, sdk):
        r = sdk.log_workout([{"exercise_name": "Curls", "sets": 1},
                             {"exercise_name": "Hammer Curls", "sets": 1}])
        assert "Hammer Curls" in r["error"]
        assert r["unknown_exercises"] == ["Hammer Curls"]
        assert sdk.search_workouts(workouts=1)["count"] == 0

    def test_log_stores_the_catalog_spelling(self, sdk):
        r = sdk.log_workout([{"exercise_name": "bench press", "sets": 1}])
        assert _day(sdk, r["date"])[0]["exercise_name"] == "Bench Press"

    def test_revise_to_unknown_exercise_is_rejected(self, sdk):
        r = sdk.log_workout([{"exercise_name": "Curls", "sets": 1}])
        bad = sdk.revise_workout_entry(r["ids"][0], {"exercise_name": "Hammer Curls"}, r["date"])
        assert "unknown_exercises" in bad
        ok = sdk.revise_workout_entry(r["ids"][0], {"exercise_name": "rows"}, r["date"])
        assert ok["success"]
        assert _day(sdk, r["date"])[0]["exercise_name"] == "Rows"

    def test_renaming_a_catalog_exercise_renames_its_log_entries(self, sdk):
        sdk._journal.append([{"exercise_name": "Curls", "sets": 1}], "2025-01-05")
        sdk._journal.append([{"exercise_name": "curls", "sets": 1}], "2025-02-05")
        sdk._journal.append([{"exercise_name": "Rows", "sets": 1}], "2025-02-05")
        r = sdk.update_exercise("Curls", {"name": "Bicep Curls"})
        assert r["log_entries_renamed"] == 2
        assert sdk._journal.count_names() == {"Bicep Curls": 2, "Rows": 1}
        assert sdk.update_exercise("Bicep Curls", {"name": "Rows"})["error"].startswith("Exercise 'Rows' already exists")

    def test_log_workout(self, sdk):
        result = sdk.log_workout([
            {"exercise_name": "Bench Press", "sets": 3, "weight": 135, "max_reps": 7},
        ])
        assert result["success"]
        assert result["entries_added"] == 1

    def test_log_workout_assigns_ids(self, sdk):
        result = sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])
        assert len(result["ids"]) == 1
        assert "id" in _day(sdk, result["date"])[0]

    def test_log_echoes_date_and_total(self, sdk):
        result = sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])
        assert result["date"]            # server-derived effective date
        assert result["total_entries"] == 1
        assert len(result["ids"]) == 1

    def test_log_multiple_exercises_same_day(self, sdk):
        sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])
        r = sdk.log_workout([{"exercise_name": "Rows", "sets": 3}])
        assert r["total_entries"] == 2
        assert len(_day(sdk, r["date"])) == 2

    def test_revise_workout_entry(self, sdk):
        r = sdk.log_workout([{"exercise_name": "Curls", "sets": 2, "weight": 30}])
        eid = r["ids"][0]
        res = sdk.revise_workout_entry(eid, {"weight": 35, "max_reps": 8})
        assert res["success"]
        assert res["total_entries"] == 1
        assert _day(sdk, r["date"])[0]["weight"] == 35

    def test_revise_nonexistent_entry(self, sdk):
        result = sdk.revise_workout_entry("bad-id", {"sets": 5})
        assert "error" in result

    def test_remove_workout_entry(self, sdk):
        r = sdk.log_workout([
            {"exercise_name": "Curls", "sets": 2},
            {"exercise_name": "Rows", "sets": 3},
        ])
        res = sdk.remove_workout_entry(r["ids"][0])
        assert res["success"]
        assert res["total_entries"] == 1
        assert len(_day(sdk, r["date"])) == 1

    def test_remove_nonexistent_entry(self, sdk):
        result = sdk.remove_workout_entry("bad-id")
        assert "error" in result

    def test_emptying_a_day_drops_the_shard_file(self, sdk):
        r = sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])
        month = r["date"][:7]
        assert (sdk._journal.dir / f"{month}.json").exists()
        sdk.remove_workout_entry(r["ids"][0])
        assert not (sdk._journal.dir / f"{month}.json").exists()


class TestWorkoutSearchReads:
    """search_workouts is a clock-free reverse scan over month shards."""

    def _seed(self, sdk):
        sdk.add_exercise("Curls", "Arms")
        sdk.add_exercise("Bench", "Chest")
        # Seed entries directly onto known dates spanning two months.
        sdk._journal.append([{"exercise_name": "Curls", "weight": 30, "max_reps": 10}], "2025-03-01")
        sdk._journal.append([{"exercise_name": "Bench", "weight": 135, "max_reps": 5}], "2025-03-10")
        sdk._journal.append([{"exercise_name": "Curls", "weight": 35, "max_reps": 9}], "2025-04-02")
        sdk._journal.append([{"exercise_name": "Curls", "weight": 40, "max_reps": 8}], "2025-04-20")

    def test_rows_most_recent_first(self, sdk):
        self._seed(sdk)
        res = sdk.search_workouts(workouts=10)
        dates = [r["date"] for r in res["rows"]]
        assert dates == ["2025-04-20", "2025-04-02", "2025-03-10", "2025-03-01"]
        assert res["has_more"] is False

    def test_empty_history_returns_no_rows(self, sdk):
        res = sdk.search_workouts()
        assert res["count"] == 0
        assert res["rows"] == []
        assert res["scanned_through"] is None

    def test_limit_and_has_more(self, sdk):
        self._seed(sdk)
        res = sdk.search_workouts(workouts=2)
        assert res["count"] == 2
        assert res["has_more"] is True

    def test_recent_read_stops_at_the_newest_shard(self, sdk):
        self._seed(sdk)
        res = sdk.search_workouts(workouts=1)
        assert res["months_scanned"] == 1
        assert res["scanned_through"] == "2025-04"

    def test_last_n_of_one_exercise(self, sdk):
        self._seed(sdk)
        res = sdk.search_workouts(exercises=["curls"], workouts=4)
        assert [r["weight"] for r in res["rows"]] == [40, 35, 30]
        assert res["filters"]["exercises"] == ["Curls"]

    def test_since_until_window_is_inclusive(self, sdk):
        self._seed(sdk)
        res = sdk.search_workouts(since="2025-03-10", until="2025-04-02")
        assert [r["date"] for r in res["rows"]] == ["2025-04-02", "2025-03-10"]

    def test_todays_workout_is_since_equals_until(self, sdk):
        self._seed(sdk)
        today = sdk._journal.today()
        sdk.log_workout([{"exercise_name": "Curls", "sets": 1, "weight": 30, "max_reps": 10}])
        res = sdk.search_workouts(since=today, until=today)
        assert res["count"] == 1 and res["rows"][0]["date"] == today


class TestWorkoutMove:
    def test_move_between_dates_cross_month(self, sdk):
        r = sdk._journal.append([{"exercise_name": "Curls", "sets": 2}], "2025-01-31")
        eid = r["ids"][0]
        res = sdk.move_workout_entries([eid], "2025-01-31", "2025-02-01")
        assert res["success"]
        assert res["source_total_entries"] == 0
        assert res["target_total_entries"] == 1
        assert _day(sdk, "2025-01-31") == []
        assert _day(sdk, "2025-02-01")[0]["id"] == eid

    def test_move_only_named_entries(self, sdk):
        r = sdk._journal.append([
            {"exercise_name": "Curls", "sets": 2},
            {"exercise_name": "Rows", "sets": 3},
        ], "2025-02-10")
        res = sdk.move_workout_entries([r["ids"][0]], "2025-02-10", "2025-02-11")
        assert res["moved"] == 1
        assert len(_day(sdk, "2025-02-10")) == 1

    def test_move_missing_id_errors(self, sdk):
        sdk._journal.append([{"exercise_name": "Curls", "sets": 2}], "2025-02-10")
        result = sdk.move_workout_entries(["nope"], "2025-02-10", "2025-02-11")
        assert "error" in result

    def test_move_same_date_rejected(self, sdk):
        result = sdk.move_workout_entries(["x"], "2025-02-02", "2025-02-02")
        assert "error" in result


class TestMigration:
    def test_folds_legacy_day_files_into_month_shards(self, sdk, tmp_path):
        import json
        wdir = sdk._journal.dir
        wdir.mkdir(parents=True, exist_ok=True)
        # Two legacy per-date files in the same month + one in another month.
        (wdir / "2025-07-04_workout.json").write_text(
            json.dumps([{"exercise_name": "Curls", "sets": 2, "id": "a1"}]))
        (wdir / "2025-07-20_workout.json").write_text(
            json.dumps([{"exercise_name": "Rows", "sets": 3, "id": "b2"}]))
        (wdir / "2025-08-01_workout.json").write_text(
            json.dumps([{"exercise_name": "Bench", "sets": 5, "id": "c3"}]))

        res = sdk.migrate_storage()
        assert res["migrated_files"] == 3
        assert res["migrated_entries"] == 3

        # Legacy files gone; month shards present and correct.
        assert not list(wdir.glob("*_workout.json"))
        assert (wdir / "2025-07.json").exists()
        assert (wdir / "2025-08.json").exists()
        assert _day(sdk, "2025-07-04")[0]["id"] == "a1"
        assert _day(sdk, "2025-07-20")[0]["id"] == "b2"
        assert _day(sdk, "2025-08-01")[0]["id"] == "c3"

    def test_migration_is_idempotent(self, sdk):
        import json
        wdir = sdk._journal.dir
        wdir.mkdir(parents=True, exist_ok=True)
        (wdir / "2025-09-09_workout.json").write_text(
            json.dumps([{"exercise_name": "Curls", "sets": 2, "id": "z9"}]))
        assert sdk.migrate_storage()["migrated_files"] == 1
        # second run is a no-op, no duplication
        assert sdk.migrate_storage()["migrated_files"] == 0
        assert len(_day(sdk, "2025-09-09")) == 1
