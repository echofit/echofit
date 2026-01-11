import os
import json
import logging
import yaml
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional, Any, Dict
from .context import current_user_id

logger = logging.getLogger(__name__)

def _get_bootstrap_settings() -> Dict[str, Any]:
    env_path = os.environ.get("FOOD_AGENT_SETTINGS")
    if env_path:
        path = Path(env_path).expanduser().resolve()
    else:
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config_home:
            base = Path(xdg_config_home)
        else:
            base = Path.home() / ".config"
        path = base / "food-agent" / "settings.json"

    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read bootstrap settings at {path}: {e}")
            return {}
    return {}

def get_app_config_dir() -> Path:
    env_path = os.environ.get("FOOD_AGENT_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()

    settings = _get_bootstrap_settings()
    if "paths" in settings and settings["paths"].get("config"):
        return Path(settings["paths"]["config"]).expanduser().resolve()

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        base_path = Path(xdg_config_home)
    else:
        base_path = Path.home() / ".config"
    return base_path / "food-agent"

def get_app_data_base_dir() -> Path:
    """Resolve the Base Data Directory (where FUSE is mounted)."""
    env_path = os.environ.get("FOOD_AGENT_DATA")
    if env_path:
        return Path(env_path).expanduser().resolve()

    settings = _get_bootstrap_settings()
    if "paths" in settings and settings["paths"].get("data"):
        return Path(settings["paths"]["data"]).expanduser().resolve()
    if settings.get("data_path"):
        return Path(settings["data_path"]).expanduser().resolve()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        base_path = Path(xdg_data_home)
    else:
        base_path = Path.home() / ".local" / "share"
    return base_path / "food-agent"

def get_app_data_dir() -> Path:
    """Resolve the User-Scoped Data Directory."""
    base = get_app_data_base_dir()
    user = current_user_id.get()
    
    if user == "default":
        return base
        
    safe_user = "".join(c if c.isalnum() or c in "-_." else "_" for c in user)
    return base / safe_user

class FoodAgentConfig:
    def __init__(self):
        self.config_dir = get_app_config_dir()
        self.package_root = Path(__file__).parent.parent
        self.project_root = self.package_root.parent
        self.schemas_dir = self.project_root / "schemas"
        self.settings_file = self.config_dir / "settings.json"
        self.app_config = self._load_app_config()
        self.day_cutoff_hour = self.app_config.get("day_cutoff_hour", 0)

    @property
    def data_dir(self) -> Path:
        return get_app_data_dir()

    @property
    def daily_log_dir(self) -> Path:
        return self.data_dir / "daily"

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "catalog"

    @property
    def catalog_file(self) -> Path:
        return self.catalog_dir / "catalog.json"

    def _load_app_config(self) -> dict:
        config_path = self.package_root / "app.yaml"
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Error loading app.yaml: {e}")
        return {}

    def get_effective_today(self) -> date:
        now = datetime.now()
        if now.hour < self.day_cutoff_hour:
            return (now - timedelta(days=1)).date()
        return now.date()

    def ensure_directories(self):
        try:
            os.makedirs(self.daily_log_dir, exist_ok=True)
            os.makedirs(self.catalog_dir, exist_ok=True)
            os.makedirs(self.config_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating directories: {e}")
            raise