import os
import json
import yaml
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from food_agent.cli.main import cli

@pytest.fixture
def temp_config_dir(tmp_path):
    """Set up a temporary config directory for testing."""
    original_env = os.environ.get("FOOD_AGENT_CONFIG")
    os.environ["FOOD_AGENT_CONFIG"] = str(tmp_path)
    yield tmp_path
    if original_env:
        os.environ["FOOD_AGENT_CONFIG"] = original_env
    else:
        del os.environ["FOOD_AGENT_CONFIG"]

def test_init_discovery_success(temp_config_dir):
    """Test 'init' with successful auto-discovery."""
    runner = CliRunner()

    with patch("food_agent.cli.cloud.get_current_gcloud_user") as mock_user, \
         patch("food_agent.cli.cloud.lookup_project_by_label") as mock_project, \
         patch("food_agent.cli.cloud.lookup_bucket_by_label") as mock_bucket:

        mock_user.return_value = "user@example.com"
        mock_project.return_value = "discovered-project"
        mock_bucket.return_value = "discovered-bucket"

        result = runner.invoke(cli, ["config", "init"])

        assert result.exit_code == 0
        assert "Configuration saved" in result.stderr

        # Verify file creation
        config_file = temp_config_dir / "admin.yaml"
        assert config_file.exists()
        with open(config_file, "r") as f:
            data = yaml.safe_load(f)
            assert data["project_id"] == "discovered-project"
            assert data["bucket_name"] == "discovered-bucket"

def test_init_discovery_fails_no_project(temp_config_dir):
    """Test 'init' fails when no project is found (and no interactive input)."""
    runner = CliRunner()

    with patch("food_agent.cli.cloud.get_current_gcloud_user") as mock_user, \
         patch("food_agent.cli.cloud.lookup_project_by_label") as mock_lookup:

        mock_user.return_value = "user@example.com"
        mock_lookup.return_value = None

        # Click will prompt if not provided. We provide empty input to simulate failure/cancel.
        result = runner.invoke(cli, ["config", "init"], input="\n")

        assert result.exit_code != 0

def test_init_discovery_fails_multiple_projects(temp_config_dir):
    """Test 'init' fails when multiple projects match the label."""
    runner = CliRunner()

    with patch("food_agent.cli.cloud.get_current_gcloud_user") as mock_user, \
         patch("subprocess.run") as mock_run:

        mock_user.return_value = "user@example.com"
        mock_run.return_value.stdout = "project-1\nproject-2"

        result = runner.invoke(cli, ["config", "init"])
        assert result.exit_code != 0
        assert "Multiple projects found" in result.stderr

def test_init_discovery_passes_single_project(temp_config_dir):
    """Test 'init' succeeds when exactly one project is found."""
    runner = CliRunner()

    with patch("food_agent.cli.cloud.get_current_gcloud_user") as mock_user, \
         patch("subprocess.run") as mock_run:

        mock_user.return_value = "user@example.com"

        def side_effect(cmd, **kwargs):
            res = MagicMock()
            if "projects" in cmd:
                res.stdout = "single-project"
            elif "storage" in cmd:
                res.stdout = "single-bucket"
            else:
                res.stdout = ""
            return res

        mock_run.side_effect = side_effect

        result = runner.invoke(cli, ["config", "init"])
        assert result.exit_code == 0

        config_file = temp_config_dir / "admin.yaml"
        with open(config_file, "r") as f:
            data = yaml.safe_load(f)
            assert data["project_id"] == "single-project"
            assert data["bucket_name"] == "single-bucket"

def test_init_custom_label(temp_config_dir):
    """Test 'init' with a custom label value."""
    runner = CliRunner()

    with patch("food_agent.cli.cloud.get_current_gcloud_user") as mock_user, \
         patch("subprocess.run") as mock_run:

        mock_user.return_value = "user@example.com"

        def side_effect(cmd, **kwargs):
            res = MagicMock()
            if "projects" in cmd:
                # check that the custom-val is in the filter arg
                filter_arg = [a for a in cmd if a.startswith("--filter")][0]
                assert "custom-val" in filter_arg
                res.stdout = "custom-project"
            elif "storage" in cmd:
                filter_arg = [a for a in cmd if a.startswith("--filter")][0]
                assert "custom-val" in filter_arg
                res.stdout = "custom-bucket"
            return res

        mock_run.side_effect = side_effect

        result = runner.invoke(cli, ["config", "init", "--label-value", "custom-val"])
        assert result.exit_code == 0

        with open(temp_config_dir / "admin.yaml", "r") as f:
            data = yaml.safe_load(f)
            assert data["label_value"] == "custom-val"

def test_resolve_success(temp_config_dir):
    """Test 'resolve' with valid configuration."""
    runner = CliRunner()
    config_data = {
        "gcloud_user": "user@example.com",
        "project_id": "target-project",
        "bucket_name": "target-bucket",
        "label_value": "default"
    }
    config_file = temp_config_dir / "admin.yaml"
    temp_config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    with patch("food_agent.cli.cloud.get_current_gcloud_user") as mock_user:
        mock_user.return_value = "user@example.com"

        result = runner.invoke(cli, ["config", "resolve"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["project_id"] == "target-project"
        assert data["bucket_name"] == "target-bucket"

def test_resolve_user_mismatch_fails(temp_config_dir):
    """Test 'resolve' fails when the gcloud user has changed."""
    runner = CliRunner()
    config_data = {"gcloud_user": "user@example.com", "project_id": "some-project"}
    config_file = temp_config_dir / "admin.yaml"
    temp_config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    with patch("food_agent.cli.cloud.get_current_gcloud_user") as mock_user:
        mock_user.return_value = "test@example.com"

        result = runner.invoke(cli, ["config", "resolve"])
        assert result.exit_code != 0
        assert "Configuration mismatch" in result.stderr
