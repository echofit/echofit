import csv
import logging
from pathlib import Path
from typing import Dict, Optional
from .config import get_app_data_dir

logger = logging.getLogger(__name__)

class UserStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        # users.csv lives in the root of the data folder (base of FUSE mount)
        self.users_file = self.data_dir / "users.csv"
        self._cache: Dict[str, str] = {} # PAT -> email

    def refresh_cache(self) -> Dict[str, str]:
        """Read users.csv from disk."""
        if not self.users_file.exists():
            logger.warning(f"User file not found at {self.users_file}")
            self._cache = {}
            return {}

        try:
            new_cache = {}
            with open(self.users_file, "r") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        pat, email = row[0], row[1]
                        new_cache[pat] = email
            self._cache = new_cache
            return self._cache
        except Exception as e:
            logger.error(f"Error reading users.csv: {e}")
            return self._cache

    def get_user_by_pat(self, pat: str) -> Optional[str]:
        """Get email for PAT, refreshing if not found."""
        if pat in self._cache:
            return self._cache[pat]
        
        self.refresh_cache()
        return self._cache.get(pat)

    def add_user(self, pat: str, email: str):
        """Append/Update user in the file."""
        self.refresh_cache()
        self._cache[pat] = email
        
        # Ensure dir exists (it's the base dir, so it should)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.users_file, "w", newline="") as f:
            writer = csv.writer(f)
            for p, e in self._cache.items():
                writer.writerow([p, e])