import os
import json
import logging
import yaml
from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Any, Dict
from .context import current_user_id

DEFAULTS = {
    "hours_offset": 4,
    "timezone": "America/Chicago",
}

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
    # APP_USERS_PATH is the standard env var set by gapp.yaml
    users_path = os.environ.get("APP_USERS_PATH")
    if users_path:
        return Path(users_path).expanduser().resolve()

    # Legacy env var
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
        
    return base / user.replace("@", "~")

class FoodAgentConfig:
    def __init__(self):
        self.config_dir = get_app_config_dir()
        self.package_root = Path(__file__).parent.parent
        self.project_root = self.package_root.parent
        self.schemas_dir = self.project_root / "schemas"
        self.settings_file = self.config_dir / "settings.json"
        self.app_config = self._load_app_config()
        self.hours_offset = self.app_config.get("hours_offset", DEFAULTS["hours_offset"])
        self.timezone = self.app_config.get("timezone", DEFAULTS["timezone"])

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
        """Determine the effective calendar date for food logging.

        Uses the configured timezone (default: America/Chicago) and
        hours_offset (default: 4). The offset shifts the day boundary
        forward from midnight — e.g. with hours_offset=4, eating at
        2 AM counts as the prior calendar day because the new day
        doesn't start until 4 AM. A negative offset shifts the boundary
        earlier (e.g. -2 means the next day starts at 10 PM).

        The math: subtract hours_offset from the current time, then
        take the date component.
        """
        tz = ZoneInfo(self.timezone)
        now = datetime.now(tz)
        adjusted = now - timedelta(hours=self.hours_offset)
        return adjusted.date()

    def get_settings(self) -> Dict[str, Any]:
        """Return all effective settings (explicit config + defaults).

        Always returns a value for every known setting, using the
        configured value if present or the built-in default otherwise.
        """
        return {
            "hours_offset": self.hours_offset,
            "timezone": self.timezone,
            "effective_date": self.get_effective_today().isoformat(),
        }

    def ensure_directories(self):
        try:
            os.makedirs(self.daily_log_dir, exist_ok=True)
            os.makedirs(self.catalog_dir, exist_ok=True)
            os.makedirs(self.config_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating directories: {e}")
            raise