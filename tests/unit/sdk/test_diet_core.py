import os
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from echofit.config import EchoFitConfig, DEFAULTS
from echofit.diet import DietSDK


@pytest.fixture
def tmp_env(tmp_path):
    """Isolated data and config dirs via env vars."""
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    config_dir.mkdir()
    with patch.dict(os.environ, {
        "ECHOFIT_DATA": str(data_dir),
        "ECHOFIT_CONFIG": str(config_dir),
    }):
        yield tmp_path


@pytest.fixture
def sdk(tmp_env):
    return DietSDK()


def _make_entry(name="Test Food"):
    return {
        "food_name": name,
        "user_description": f"a {name.lower()}",
        "standard_serving": {
            "size": {"amount": 1, "unit": "serving"},
            "nutrition": {
                "calories": 100, "protein": 5, "carbs": 10,
                "fat": 3, "sodium": 50, "potassium": 100,
                "fiber": 2, "sugar": 5,
            },
        },
        "consumed": {
            "size": {"amount": 1, "unit": "serving"},
            "standard_servings": 1,
            "nutrition": {
                "calories": 100, "protein": 5, "carbs": 10,
                "fat": 3, "sodium": 50, "potassium": 100,
                "fiber": 2, "sugar": 5,
            },
            "verified_calculation": True,
        },
        "confidence_score": 8,
    }


# --- Effective date calculation ---

class TestEffectiveDate:
    def test_afternoon_is_same_day(self, tmp_env):
        """Eating at 2 PM Central yields today's date."""
        tz = ZoneInfo("America/Chicago")
        fake_now = datetime(2026, 3, 15, 14, 0, tzinfo=tz)
        with patch("echofit.config.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            config = EchoFitConfig()
            assert config.get_effective_today().isoformat() == "2026-03-15"

    def test_2am_counts_as_prior_day(self, tmp_env):
        """Eating at 2 AM Central (before 4 AM offset) yields yesterday."""
        tz = ZoneInfo("America/Chicago")
        fake_now = datetime(2026, 3, 15, 2, 0, tzinfo=tz)
        with patch("echofit.config.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            config = EchoFitConfig()
            assert config.get_effective_today().isoformat() == "2026-03-14"

    def test_exactly_4am_is_new_day(self, tmp_env):
        """Eating at exactly 4 AM Central starts the new day."""
        tz = ZoneInfo("America/Chicago")
        fake_now = datetime(2026, 3, 15, 4, 0, tzinfo=tz)
        with patch("echofit.config.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            config = EchoFitConfig()
            assert config.get_effective_today().isoformat() == "2026-03-15"

    def test_defaults_used_when_app_yaml_missing(self, tmp_env):
        """Config falls back to DEFAULTS when app.yaml is absent."""
        config = EchoFitConfig()
        assert config.hours_offset == DEFAULTS["hours_offset"]
        assert config.timezone == DEFAULTS["timezone"]


# --- log_food ---

class TestLogFood:
    def test_log_food_assigns_id(self, sdk):
        """Each logged entry gets a unique ID."""
        result = sdk.log_food([_make_entry()])
        assert result["success"]

        log = sdk.get_food_log(result["date"])
        items = log["items"]
        assert len(items) == 1
        assert "id" in items[0]
        assert len(items[0]["id"]) == 12

    def test_log_food_ids_are_unique(self, sdk):
        """Multiple entries in one call get distinct IDs."""
        result = sdk.log_food([_make_entry("Apple"), _make_entry("Banana")])
        assert result["entries_added"] == 2

        log = sdk.get_food_log(result["date"])
        ids = [item["id"] for item in log["items"]]
        assert len(set(ids)) == 2

    def test_log_food_returns_effective_date(self, sdk):
        """The response includes which date entries were logged against."""
        result = sdk.log_food([_make_entry()])
        assert "date" in result
        # Should be a valid YYYY-MM-DD string
        datetime.strptime(result["date"], "%Y-%m-%d")

    def test_log_food_no_date_parameter(self, sdk):
        """log_food does not accept an entry_date parameter."""
        import inspect
        sig = inspect.signature(sdk.log_food)
        assert "entry_date" not in sig.parameters


# --- move_log_entries ---

class TestMoveLogEntries:
    def test_move_entries_between_dates(self, sdk):
        """Entries are removed from source and appear on target."""
        result = sdk.log_food([_make_entry("Apple"), _make_entry("Banana")])
        source_date = result["date"]
        target_date = "2026-01-01"

        log = sdk.get_food_log(source_date)
        apple_id = next(i["id"] for i in log["items"] if i["food_name"] == "Apple")

        move_result = sdk.move_log_entries([apple_id], source_date, target_date)
        assert move_result["success"]
        assert "Apple" in move_result["moved_entries"]

        # Source should only have Banana
        source_log = sdk.get_food_log(source_date)
        assert len(source_log["items"]) == 1
        assert source_log["items"][0]["food_name"] == "Banana"

        # Target should have Apple
        target_log = sdk.get_food_log(target_date)
        assert len(target_log["items"]) == 1
        assert target_log["items"][0]["food_name"] == "Apple"

    def test_move_all_entries_removes_source_file(self, sdk):
        """Moving all entries from a date deletes the source file."""
        result = sdk.log_food([_make_entry()])
        source_date = result["date"]
        entry_id = sdk.get_food_log(source_date)["items"][0]["id"]

        sdk.move_log_entries([entry_id], source_date, "2026-01-01")

        source_file = sdk.config.daily_log_dir / f"{source_date}_food-log.json"
        assert not source_file.exists()

    def test_move_rejects_same_date(self, sdk):
        """Cannot move entries to the same date."""
        result = sdk.log_food([_make_entry()])
        d = result["date"]
        entry_id = sdk.get_food_log(d)["items"][0]["id"]

        move_result = sdk.move_log_entries([entry_id], d, d)
        assert "error" in move_result

    def test_move_rejects_missing_ids(self, sdk):
        """Returns error when entry IDs are not found on source date."""
        result = sdk.log_food([_make_entry()])
        d = result["date"]

        move_result = sdk.move_log_entries(["nonexistent"], d, "2026-01-01")
        assert "error" in move_result

    def test_move_rejects_invalid_date_format(self, sdk):
        """Returns error for malformed dates."""
        move_result = sdk.move_log_entries(["abc"], "bad-date", "2026-01-01")
        assert "error" in move_result

    def test_move_appends_to_existing_target(self, sdk):
        """Moving to a date that already has entries appends, not overwrites."""
        # Log to target date first
        tz = ZoneInfo("America/Chicago")
        fake_now = datetime(2026, 1, 1, 12, 0, tzinfo=tz)
        with patch("echofit.config.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            sdk2 = DietSDK()
            sdk2.log_food([_make_entry("Existing")])

        # Log to a different date and move to target
        result = sdk.log_food([_make_entry("Moved")])
        source_date = result["date"]
        entry_id = sdk.get_food_log(source_date)["items"][-1]["id"]

        if source_date != "2026-01-01":
            sdk.move_log_entries([entry_id], source_date, "2026-01-01")

        target_log = sdk.get_food_log("2026-01-01")
        names = [i["food_name"] for i in target_log["items"]]
        assert "Existing" in names
        assert "Moved" in names


# --- get_settings ---

class TestGetSettings:
    def test_returns_all_settings_with_defaults(self, sdk):
        """get_settings returns timezone, hours_offset, and effective_date."""
        settings = sdk.get_settings()
        assert "timezone" in settings
        assert "hours_offset" in settings
        assert "effective_date" in settings
        assert settings["timezone"] == "America/Chicago"
        assert settings["hours_offset"] == 4

    def test_effective_date_is_valid_iso(self, sdk):
        """effective_date is a valid YYYY-MM-DD string."""
        settings = sdk.get_settings()
        datetime.strptime(settings["effective_date"], "%Y-%m-%d")
