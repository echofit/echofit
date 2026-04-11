"""Catalog CRUD tests for DietSDK.

Covers the five SDK methods wired to MCP tools:
  - get_catalog (show_food_catalog)
  - add_to_catalog (add_food_to_catalog)
  - update_catalog_item (update_food_in_catalog)
  - remove_from_catalog (remove_food_from_catalog)

Plus revise_log_entry (revise_food_log_entry), which works on the
food log rather than the catalog but shares the same CRUD shape.

These were surfaced as gaps by the mcp-app framework's
`mcp_app.testing.tools.test_sdk_coverage_audit`. See echofit/echofit#4.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from echofit.diet import DietSDK


@pytest.fixture
def tmp_env(tmp_path):
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


def _catalog_item(name: str, calories: int = 100) -> dict:
    return {
        "food_name": name,
        "user_description": f"a {name.lower()}",
        "standard_serving": {
            "size": {"amount": 1, "unit": "serving"},
            "nutrition": {
                "calories": calories,
                "protein": 5, "carbs": 10, "fat": 3,
                "sodium": 50, "potassium": 100, "fiber": 2, "sugar": 5,
            },
        },
    }


def _log_entry(name: str) -> dict:
    return {
        "food_name": name,
        "consumed": {
            "nutrition": {
                "calories": 100, "protein": 5, "carbs": 10, "fat": 3,
            },
        },
        "confidence_score": 8,
    }


class TestAddToCatalog:
    def test_adds_new_item(self, sdk):
        result = sdk.add_to_catalog(_catalog_item("Apple"))
        assert result["success"] is True
        assert "Apple" in result["message"]

    def test_persists_item_to_catalog(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        catalog = sdk.get_catalog()
        names = [i["food_name"] for i in catalog["items"]]
        assert "Apple" in names

    def test_rejects_missing_food_name(self, sdk):
        result = sdk.add_to_catalog({"user_description": "mystery"})
        assert "error" in result

    def test_rejects_duplicate_name_case_insensitive(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        result = sdk.add_to_catalog(_catalog_item("apple"))
        assert "error" in result
        assert "already exists" in result["error"]


class TestGetCatalog:
    def test_empty_catalog_returns_zero_count(self, sdk):
        result = sdk.get_catalog()
        assert result["items"] == []
        assert result["count"] == 0

    def test_returns_all_items_when_no_filter(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        sdk.add_to_catalog(_catalog_item("Banana"))
        sdk.add_to_catalog(_catalog_item("Cherry"))
        result = sdk.get_catalog()
        assert result["count"] == 3

    def test_filters_by_substring(self, sdk):
        sdk.add_to_catalog(_catalog_item("Red Apple"))
        sdk.add_to_catalog(_catalog_item("Green Apple"))
        sdk.add_to_catalog(_catalog_item("Banana"))
        result = sdk.get_catalog(filter_text="apple")
        assert result["count"] == 2
        names = [i["food_name"] for i in result["items"]]
        assert all("Apple" in n for n in names)

    def test_filter_is_case_insensitive(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        result = sdk.get_catalog(filter_text="APPLE")
        assert result["count"] == 1

    def test_filter_accepts_list_of_terms(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        sdk.add_to_catalog(_catalog_item("Banana"))
        sdk.add_to_catalog(_catalog_item("Cherry"))
        result = sdk.get_catalog(filter_text=["apple", "cherry"])
        assert result["count"] == 2

    def test_regex_filter(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple Pie"))
        sdk.add_to_catalog(_catalog_item("Banana Bread"))
        sdk.add_to_catalog(_catalog_item("Cherry Pie"))
        result = sdk.get_catalog(filter_text=r".*Pie$", use_regex=True)
        assert result["count"] == 2


class TestUpdateCatalogItem:
    def test_updates_existing_item_fields(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple", calories=100))
        result = sdk.update_catalog_item("Apple", {"user_description": "a red apple"})
        assert result["success"] is True
        catalog = sdk.get_catalog()
        apple = next(i for i in catalog["items"] if i["food_name"] == "Apple")
        assert apple["user_description"] == "a red apple"

    def test_update_is_case_insensitive_on_name(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        result = sdk.update_catalog_item("APPLE", {"user_description": "uppercase match"})
        assert result["success"] is True

    def test_update_missing_item_returns_error(self, sdk):
        result = sdk.update_catalog_item("Nonexistent", {"user_description": "x"})
        assert "error" in result
        assert "not found" in result["error"]


class TestRemoveFromCatalog:
    def test_removes_existing_item(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        sdk.add_to_catalog(_catalog_item("Banana"))
        result = sdk.remove_from_catalog("Apple")
        assert result["success"] is True
        catalog = sdk.get_catalog()
        names = [i["food_name"] for i in catalog["items"]]
        assert "Apple" not in names
        assert "Banana" in names

    def test_remove_is_case_insensitive(self, sdk):
        sdk.add_to_catalog(_catalog_item("Apple"))
        result = sdk.remove_from_catalog("APPLE")
        assert result["success"] is True
        assert sdk.get_catalog()["count"] == 0

    def test_remove_missing_item_returns_error(self, sdk):
        result = sdk.remove_from_catalog("Nonexistent")
        assert "error" in result
        assert "not found" in result["error"]


class TestReviseLogEntry:
    def test_revises_existing_entry_on_current_date(self, sdk):
        log_result = sdk.log_food([_log_entry("Apple")])
        date = log_result["date"]
        result = sdk.revise_log_entry(
            "Apple",
            {"consumed": {"nutrition": {"calories": 150}}},
            entry_date=date,
        )
        assert result["success"] is True
        assert result["date"] == date

    def test_revise_persists_update_to_disk(self, sdk):
        log_result = sdk.log_food([_log_entry("Apple")])
        date = log_result["date"]
        sdk.revise_log_entry(
            "Apple",
            {"user_description": "revised"},
            entry_date=date,
        )
        log_file = sdk.config.daily_log_dir / f"{date}_food-log.json"
        entries = json.loads(log_file.read_text())
        apple = next(e for e in entries if e["food_name"] == "Apple")
        assert apple["user_description"] == "revised"

    def test_revise_without_date_targets_effective_today(self, sdk):
        sdk.log_food([_log_entry("Apple")])
        result = sdk.revise_log_entry("Apple", {"user_description": "today"})
        assert result["success"] is True

    def test_revise_missing_entry_returns_error(self, sdk):
        log_result = sdk.log_food([_log_entry("Apple")])
        date = log_result["date"]
        result = sdk.revise_log_entry(
            "Nonexistent",
            {"user_description": "x"},
            entry_date=date,
        )
        assert "error" in result
        assert "No entry found" in result["error"]

    def test_revise_with_invalid_date_format_returns_error(self, sdk):
        result = sdk.revise_log_entry(
            "Apple",
            {"user_description": "x"},
            entry_date="not-a-date",
        )
        assert "error" in result
        assert "Invalid date format" in result["error"]

    def test_revise_on_date_with_no_log_returns_error(self, sdk):
        result = sdk.revise_log_entry(
            "Apple",
            {"user_description": "x"},
            entry_date="2020-01-01",
        )
        assert "error" in result
