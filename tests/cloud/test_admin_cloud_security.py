import os
import json
import subprocess
import requests
import pytest

def get_admin_params():
    """Resolve live Cloud Run Admin configuration."""
    try:
        # 1. Get Project ID
        res = subprocess.run(
            ["python3", "-m", "food_agent.cli.main", "config", "resolve"],
            capture_output=True, text=True, check=True
        )
        ctx = json.loads(res.stdout)
        pid = ctx.get("project_id")
        
        # 2. Get Service URL and Shared Secret via gcloud
        res_svc = subprocess.run(
            ["gcloud", "run", "services", "describe", "food-agent-admin", 
             "--project", pid, "--region", "us-central1", "--format=json"],
            capture_output=True, text=True, check=True
        )
        svc_data = json.loads(res_svc.stdout)
        url = svc_data["status"]["url"]
        
        # Extract secret from env vars
        containers = svc_data.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        if not containers:
            containers = svc_data.get("template", {}).get("containers", [])
            
        secret = None
        for c in containers:
            for env in c.get("env", []):
                if env.get("name") == "ADMIN_SHARED_SECRET":
                    secret = env.get("value")
                    break
        
        # 3. Get OIDC Token
        res_token = subprocess.run(["gcloud", "auth", "print-identity-token"], capture_output=True, text=True, check=True)
        token = res_token.stdout.strip()
        
        return {"url": url, "secret": secret, "token": token}, None
    except Exception as e:
        return None, str(e)

def test_with_full_auth_works():
    """Valid IAM Token + Valid Shared Secret -> Success."""
    params, error = get_admin_params()
    if error:
        pytest.skip(f"Cloud admin testing environment not ready: {error}")

    headers = {
        "Authorization": f"Bearer {params['token']}",
        "X-Admin-Secret": params["secret"]
    }
    res = requests.get(f"{params['url']}/admin/users", headers=headers, timeout=10)
    assert res.status_code == 200, f"Full auth failed: {res.text}"

def test_with_no_iam_fails():

    """Valid Shared Secret BUT Missing IAM Token -> Forbidden (Cloud Run Layer)."""

    params, error = get_admin_params()

    if error:

        pytest.skip(f"Cloud admin testing environment not ready: {error}")



    headers = {

        "X-Admin-Secret": params["secret"]

    }

    # Should be blocked by Cloud Run IAM (403)

    res = requests.get(f"{params['url']}/admin/users", headers=headers, timeout=10)

    assert res.status_code == 403

    # Cloud Run's default forbidden message is usually empty or 'Forbidden'

    assert "Forbidden" in res.text



def test_with_no_shared_secret_fails():

    """Valid IAM Token BUT Missing Shared Secret -> Forbidden (App Layer)."""

    params, error = get_admin_params()

    if error:

        pytest.skip(f"Cloud admin testing environment not ready: {error}")



    headers = {

        "Authorization": f"Bearer {params['token']}"

    }

    # Should be blocked by App SecretMiddleware (403)

    res = requests.get(f"{params['url']}/admin/users", headers=headers, timeout=10)

    assert res.status_code == 403

    # Our app returns "Forbidden: Missing Authentication"

    assert "Missing Authentication" in res.text
