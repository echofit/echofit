"""Storage namespace safety: echofit domain data must cohabit the per-user
directory with the framework's identity record without ever colliding, and
the two path resolvers must not drift apart.

Background: in cloud mode both mcp-app's FileSystemUserDataStore and
echofit's get_app_data_dir() resolve the per-user directory from
APP_USERS_PATH with the same @->~ encoding, so the framework's user.json
and echofit's journals live in the SAME directory. They stay safe only as
long as (a) echofit writes strictly inside namespace subdirs, never the
reserved root key, and (b) the two resolvers agree on the directory. These
tests lock both in.
"""

import os
import pytest
from unittest.mock import patch

from mcp_app.models import UserRecord
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.bridge import DataStoreAuthAdapter

from echofit import APP_NAME
from echofit.config import EchoFitConfig, get_app_data_dir
from echofit.context import current_user
from echofit.journal import DailyJournal, FRAMEWORK_RESERVED_ROOT_KEY
from echofit.workout import WorkoutSDK


@pytest.fixture
def cloud_env(tmp_path):
    """Cloud regime: APP_USERS_PATH set, a real per-user identity."""
    users_path = tmp_path / "users"
    users_path.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    with patch.dict(os.environ, {
        "APP_USERS_PATH": str(users_path),
        "ECHOFIT_CONFIG": str(config_dir),
    }):
        token = current_user.set(UserRecord(email="alice@example.com"))
        try:
            yield users_path
        finally:
            current_user.reset(token)


def test_echofit_user_dir_matches_framework_user_dir(cloud_env):
    """The dir echofit writes domain data into is the SAME dir the framework
    stores the user's auth record in — so they cohabit, and the resolvers
    have not drifted apart."""
    store = FileSystemUserDataStore(app_name=APP_NAME)
    framework_user_dir = store._key_path("alice@example.com", DataStoreAuthAdapter.USER_KEY).parent
    assert get_app_data_dir() == framework_user_dir


def test_domain_data_never_collides_with_reserved_root_key(cloud_env):
    """Logging domain data must not create {user_dir}/user.json (the
    framework's identity record) and must write under a namespace subdir."""
    sdk = WorkoutSDK()
    sdk.log_workout([{"exercise_name": "Curls", "sets": 2}])

    user_dir = get_app_data_dir()
    reserved = user_dir / f"{FRAMEWORK_RESERVED_ROOT_KEY}.json"
    assert not reserved.exists(), "echofit clobbered the framework's identity record"
    assert (user_dir / "workouts").is_dir(), "domain data must live under a subdir"


def test_reserved_key_tracks_framework_constant():
    """Our reserved-root guard is tied to the framework's actual key, so it
    can't silently fall out of sync."""
    assert FRAMEWORK_RESERVED_ROOT_KEY == DataStoreAuthAdapter.USER_KEY


class TestDailyJournalGuards:
    def test_rejects_reserved_root_subdir(self):
        cfg = EchoFitConfig()
        with pytest.raises(ValueError):
            DailyJournal(cfg, subdir=FRAMEWORK_RESERVED_ROOT_KEY)

    def test_rejects_empty_subdir(self):
        cfg = EchoFitConfig()
        with pytest.raises(ValueError):
            DailyJournal(cfg, subdir="")

    def test_append_is_append_only_no_public_replace(self):
        """The provider exposes no public way to replace a whole shard; the
        only full-shard writer is the private _write_shard."""
        assert not hasattr(DailyJournal, "set_day")
        assert not hasattr(DailyJournal, "save_day")
        assert not hasattr(DailyJournal, "set_shard")
        assert "_write_shard" in vars(DailyJournal)
