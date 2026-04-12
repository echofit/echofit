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


class TestWorkoutLogging:
    def test_log_workout(self, sdk):
        result = sdk.log_workout([
            {"exercise_name": "Bench Press", "sets": 3, "weight": 135, "max_reps": 7},
        ])
        assert result["success"]
        assert result["entries_added"] == 1

    def test_log_workout_assigns_ids(self, sdk):
        sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])
        log = sdk.get_workout_log()
        assert "id" in log["entries"][0]

    def test_get_workout_log_empty_date(self, sdk):
        result = sdk.get_workout_log()
        assert result["entries"] == []

    def test_get_workout_log_specific_date(self, sdk):
        result = sdk.get_workout_log("2025-01-15")
        assert result["date"] == "2025-01-15"

    def test_get_workout_log_invalid_date(self, sdk):
        result = sdk.get_workout_log("not-a-date")
        assert "error" in result

    def test_log_multiple_exercises_same_day(self, sdk):
        sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])
        sdk.log_workout([{"exercise_name": "Rows", "sets": 3}])
        log = sdk.get_workout_log()
        assert len(log["entries"]) == 2

    def test_revise_workout_entry(self, sdk):
        sdk.log_workout([{"exercise_name": "Curls", "sets": 2, "weight": 30}])
        log = sdk.get_workout_log()
        entry_id = log["entries"][0]["id"]
        result = sdk.revise_workout_entry(entry_id, {"weight": 35, "max_reps": 8})
        assert result["success"]
        updated = sdk.get_workout_log()
        assert updated["entries"][0]["weight"] == 35

    def test_revise_nonexistent_entry(self, sdk):
        result = sdk.revise_workout_entry("bad-id", {"sets": 5})
        assert "error" in result

    def test_remove_workout_entry(self, sdk):
        sdk.log_workout([
            {"exercise_name": "Curls", "sets": 2},
            {"exercise_name": "Rows", "sets": 3},
        ])
        log = sdk.get_workout_log()
        entry_id = log["entries"][0]["id"]
        result = sdk.remove_workout_entry(entry_id)
        assert result["success"]
        after = sdk.get_workout_log()
        assert len(after["entries"]) == 1

    def test_remove_nonexistent_entry(self, sdk):
        result = sdk.remove_workout_entry("bad-id")
        assert "error" in result
