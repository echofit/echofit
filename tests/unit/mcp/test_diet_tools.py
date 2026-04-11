"""MCP diet tool transport tests.

Prove that MCP tool functions correctly delegate to SDK and that
user identity resolution produces the right data paths.
These call the async tool functions directly — no server, no network.
"""

import os
import json
import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch
from mcp_app.models import UserRecord
from echofit.context import current_user


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
        yield data_dir


def _make_entry(name="Test Food"):
    return {
        "food_name": name,
        "consumed": {
            "nutrition": {
                "calories": 100, "protein": 5, "carbs": 10, "fat": 3,
            },
        },
        "confidence_score": 8,
    }


class TestDietToolsDelegateToSDK:
    def test_log_meal_returns_success(self, tmp_env):
        """log_meal tool function delegates to SDK and returns success."""
        from echofit_mcp.diet.tools import log_meal
        result = asyncio.run(log_meal([_make_entry()]))
        assert result["success"]
        assert "date" in result
        assert result["entries_added"] == 1

    def test_get_food_log_returns_logged_entry(self, tmp_env):
        """get_food_log tool returns entries logged via log_meal."""
        from echofit_mcp.diet.tools import log_meal, get_food_log
        log_result = asyncio.run(log_meal([_make_entry("Apple")]))
        get_result = asyncio.run(get_food_log(entry_date=log_result["date"]))
        names = [i["food_name"] for i in get_result["items"]]
        assert "Apple" in names

    def test_get_food_log_settings_returns_config(self, tmp_env):
        """get_food_log_settings tool returns timezone and offset."""
        from echofit_mcp.diet.tools import get_food_log_settings
        result = asyncio.run(get_food_log_settings())
        assert "timezone" in result
        assert "hours_offset" in result


class TestUserDataIsolation:
    def test_default_user_writes_to_base_dir(self, tmp_env):
        """Single-user (stdio) mode writes directly to base data dir."""
        from echofit_mcp.diet.tools import log_meal
        token = current_user.set(UserRecord(email="local"))
        try:
            asyncio.run(log_meal([_make_entry()]))
            assert (tmp_env / "daily").exists()
            assert len(list((tmp_env / "daily").iterdir())) == 1
        finally:
            current_user.reset(token)

    def test_authenticated_user_writes_to_user_subdir(self, tmp_env):
        """Multi-user (HTTP) mode writes to user-scoped subdirectory."""
        from echofit_mcp.diet.tools import log_meal
        token = current_user.set(UserRecord(email="alice@example.com"))
        try:
            asyncio.run(log_meal([_make_entry()]))
            user_dir = tmp_env / "alice~example.com"
            assert (user_dir / "daily").exists()
            assert len(list((user_dir / "daily").iterdir())) == 1
        finally:
            current_user.reset(token)

    def test_two_users_data_isolated(self, tmp_env):
        """Two users' data lands in separate directories."""
        from echofit_mcp.diet.tools import log_meal

        # Alice logs
        token = current_user.set(UserRecord(email="alice@example.com"))
        try:
            asyncio.run(log_meal([_make_entry("Alice Food")]))
        finally:
            current_user.reset(token)

        # Bob logs
        token = current_user.set(UserRecord(email="bob@example.com"))
        try:
            asyncio.run(log_meal([_make_entry("Bob Food")]))
        finally:
            current_user.reset(token)

        # Each has their own dir with one log file
        alice_daily = tmp_env / "alice~example.com" / "daily"
        bob_daily = tmp_env / "bob~example.com" / "daily"
        assert alice_daily.exists()
        assert bob_daily.exists()
        assert len(list(alice_daily.iterdir())) == 1
        assert len(list(bob_daily.iterdir())) == 1

        # Alice's data contains Alice Food, not Bob Food
        alice_log = json.loads(list(alice_daily.iterdir())[0].read_text())
        bob_log = json.loads(list(bob_daily.iterdir())[0].read_text())
        assert alice_log[0]["food_name"] == "Alice Food"
        assert bob_log[0]["food_name"] == "Bob Food"
