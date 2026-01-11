import os
import pytest
from pathlib import Path
from unittest.mock import patch
from food_agent.sdk.config import get_app_data_dir
from food_agent.sdk.context import current_user_id

@pytest.fixture
def mock_data_env(tmp_path):
    """Set up a mock FOOD_AGENT_DATA environment variable."""
    data_path = tmp_path / "data"
    data_path.mkdir()
    
    with patch.dict(os.environ, {"FOOD_AGENT_DATA": str(data_path)}):
        yield data_path

def test_load_single_user_data(mock_data_env):
    """Verify data path for single-user (local/default) environment."""
    # Ensure context is default
    token = current_user_id.set("default")
    try:
        resolved_path = get_app_data_dir()
        
        # In single user mode ("default"), we expect it to use the base path directly
        # to maintain backward compatibility with local usage.
        assert resolved_path == mock_data_env
        assert resolved_path.name == "data"
    finally:
        current_user_id.reset(token)

def test_load_multi_user_data(mock_data_env):
    """Verify data path for multi-user (cloud/authenticated) environment."""
    user_email = "test@example.com"
    expected_folder = "test_example.com" # derived from sanitization logic (@ -> _)
    
    # Simulate authenticated context
    token = current_user_id.set(user_email)
    try:
        resolved_path = get_app_data_dir()
        
        # In multi-user mode, we expect a subdirectory
        assert resolved_path == mock_data_env / expected_folder
        assert resolved_path.name == expected_folder
    finally:
        current_user_id.reset(token)
