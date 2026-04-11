import os
import pytest
from unittest.mock import patch
from mcp_app.models import UserRecord
from echofit.config import get_app_data_dir
from echofit.context import current_user


@pytest.fixture
def mock_data_env(tmp_path):
    """Set up a mock ECHOFIT_DATA environment variable."""
    data_path = tmp_path / "data"
    data_path.mkdir()

    with patch.dict(os.environ, {"ECHOFIT_DATA": str(data_path)}):
        yield data_path


def test_load_single_user_data(mock_data_env):
    """Verify data path for single-user (stdio) environment."""
    token = current_user.set(UserRecord(email="local"))
    try:
        resolved_path = get_app_data_dir()
        assert resolved_path == mock_data_env
        assert resolved_path.name == "data"
    finally:
        current_user.reset(token)


def test_load_multi_user_data(mock_data_env):
    """Verify data path for multi-user (HTTP) environment."""
    user_email = "test@example.com"
    expected_folder = "test~example.com"

    token = current_user.set(UserRecord(email=user_email))
    try:
        resolved_path = get_app_data_dir()
        assert resolved_path == mock_data_env / expected_folder
        assert resolved_path.name == expected_folder
    finally:
        current_user.reset(token)
