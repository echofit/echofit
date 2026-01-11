import os
import pytest
from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch

# --- Middleware Unit Tests ---

def test_middleware_rejects_missing_header():
    # Mock env vars BEFORE import to pass startup check
    with patch.dict(os.environ, {"USERS_BUCKET_NAME": "test-bucket", "ADMIN_SHARED_SECRET": "x" * 32}):
        import sys
        import importlib
        # Ensure we load a fresh version of the module with our mocked env
        if "food_agent.admin_service.app" in sys.modules:
            importlib.reload(sys.modules["food_agent.admin_service.app"])
        else:
            import food_agent.admin_service.app
            
        from food_agent.admin_service.app import SecretMiddleware
        from starlette.applications import Starlette
        from starlette.middleware import Middleware

        app = Starlette(middleware=[Middleware(SecretMiddleware)])
        
        @app.route("/")
        def homepage(request):
            return JSONResponse({"data": "secret"})

        client = TestClient(app)
        response = client.get("/admin/users")
        assert response.status_code == 403
        assert response.json() == {"error": "Forbidden: Missing Authentication"}

def test_middleware_rejects_invalid_secret():
    with patch.dict(os.environ, {"USERS_BUCKET_NAME": "test-bucket", "ADMIN_SHARED_SECRET": "A" * 32}):
        import sys
        import importlib
        if "food_agent.admin_service.app" in sys.modules:
            importlib.reload(sys.modules["food_agent.admin_service.app"])
        else:
            import food_agent.admin_service.app
            
        from food_agent.admin_service.app import SecretMiddleware
        from starlette.applications import Starlette
        from starlette.middleware import Middleware

        app = Starlette(middleware=[Middleware(SecretMiddleware)])
        
        @app.route("/")
        def homepage(request):
            return JSONResponse({"data": "secret"})

        client = TestClient(app)
        response = client.get("/admin/users", headers={"X-Admin-Secret": "WrongSecret" * 4})
        assert response.status_code == 403
        assert "Invalid Shared Secret" in response.json()["error"]

def test_middleware_accepts_valid_secret():
    valid_secret = "B" * 32
    with patch.dict(os.environ, {"USERS_BUCKET_NAME": "test-bucket", "ADMIN_SHARED_SECRET": valid_secret}):
        import sys
        import importlib
        if "food_agent.admin_service.app" in sys.modules:
            importlib.reload(sys.modules["food_agent.admin_service.app"])
        else:
            import food_agent.admin_service.app
            
        from food_agent.admin_service.app import app

        client = TestClient(app)
        response = client.get("/health", headers={"X-Admin-Secret": valid_secret})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

# --- Startup Logic Tests ---

def test_startup_fails_missing_secret():
    """Verify the app crashes if ADMIN_SHARED_SECRET is missing."""
    import subprocess
    import sys
    
    # We use a script that tries to import the app
    # We must ensure the env is clean
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    if "ADMIN_SHARED_SECRET" in env:
        del env["ADMIN_SHARED_SECRET"]
    
    # Force USERS_BUCKET_NAME to be present
    env["USERS_BUCKET_NAME"] = "test"

    cmd = [sys.executable, "-c", "from food_agent.admin_service import app"]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    assert result.returncode != 0
    assert "Security Violation: ADMIN_SHARED_SECRET is required" in result.stderr

def test_startup_fails_weak_secret():
    """Verify the app crashes if secret is too short."""
    import subprocess
    import sys
    
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    env["USERS_BUCKET_NAME"] = "test"
    env["ADMIN_SHARED_SECRET"] = "too-short" # < 32

    cmd = [sys.executable, "-c", "from food_agent.admin_service import app"]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    assert result.returncode != 0
    assert "too weak" in result.stderr
