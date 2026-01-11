import os
import json
import pytest
from pathlib import Path
from starlette.testclient import TestClient
from unittest.mock import patch
from food_agent.sdk.context import current_user_id

# --- Setup Fixture ---

@pytest.fixture
def test_env(tmp_path):
    """Sets up a fully isolated environment with files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # 1. Setup users.csv (Root of data dir)
    users_file = data_dir / "users.csv"
    users_file.write_text("test-pat,user@example.com\n")
    
    # 2. Setup user-specific log (Subfolder)
    user_dir = data_dir / "user_example.com"
    log_dir = user_dir / "daily"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "2026-01-10_food-log.json"
    
    dummy_log = [{
        "food_name": "Test Burger",
        "consumed": {"nutrition": {"calories": 500, "protein": 20, "carbs": 30, "fat": 20}}
    }]
    log_file.write_text(json.dumps(dummy_log))
    
    # 3. Set Env Vars
    with patch.dict(os.environ, {
        "FOOD_AGENT_DATA": str(data_dir),
        "USERS_BUCKET_NAME": "not-used",
        "MCP_ALLOWED_HOSTS": "testserver,custom-host.example.com"
    }):
        # Force fresh imports or reloads if needed
        # We'll reload config/core to ensure properties use the new env
        import importlib
        import food_agent.sdk.config
        import food_agent.sdk.users # UserStore
        import food_agent.mcp_service.app
        
        importlib.reload(food_agent.sdk.config)
        importlib.reload(food_agent.sdk.users)
        importlib.reload(food_agent.mcp_service.app)
        
        yield {
            "data_dir": data_dir,
            "app": food_agent.mcp_service.app.app
        }

# --- Tests ---

def test_auth_via_local_csv(test_env):
    """Verify that MCP server authenticates via local users.csv."""
    with TestClient(test_env["app"]) as client:
        # 1. Unauthorized
        # Use root / since we are in stateless mode
        res = client.post("/", json={})
        assert res.status_code == 401
        
        # 2. Authorized (Reads users.csv)
        # We expect 400 Bad Request (invalid MCP payload) but NOT 401/403
        res = client.post("/", json={}, headers={
            "Authorization": "Bearer test-pat",
            "Accept": "application/json"
        })
        assert res.status_code == 400
        assert "session_id" in res.text.lower() or "json-rpc" in res.text.lower() or "method" in res.text.lower()

def test_data_retrieval_segregated(test_env):
    """Verify that authenticated calls retrieve user-specific data from subfolders."""
    from food_agent.sdk.core import FoodAgentSDK
    from food_agent.sdk.config import FoodAgentConfig
    
    # Simulate the context set by middleware
    token = current_user_id.set("user@example.com")
    try:
        sdk = FoodAgentSDK()
        log = sdk.get_food_log(entry_date="2026-01-10")
        
        # Verify it found the burger in the subfolder
        assert len(log["items"]) == 1
        assert log["items"][0]["food_name"] == "Test Burger"
        assert log["totals"]["calories"] == 500
    finally:
        current_user_id.reset(token)

def test_data_retrieval_default_local(test_env):
    """Verify that local (default) calls use the base folder (backward compat)."""
    from food_agent.sdk.core import FoodAgentSDK
    
    # 1. Create a log in the ROOT (default) location
    log_dir = test_env["data_dir"] / "daily"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "2026-01-10_food-log.json"
    log_file.write_text(json.dumps([{"food_name": "Local Coffee", "consumed": {"nutrition": {"calories": 5}}}]))
    
    # Context is "default" (initial state)
    assert current_user_id.get() == "default"
    
    sdk = FoodAgentSDK()
    log = sdk.get_food_log(entry_date="2026-01-10")
    
    assert log["items"][0]["food_name"] == "Local Coffee"
