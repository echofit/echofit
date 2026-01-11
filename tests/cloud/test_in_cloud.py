import os
import json
import subprocess
import requests
import pytest
from datetime import date

def get_mcp_config():
    """Resolve live Cloud Run MCP configuration."""
    try:
        # 1. Load local context
        res = subprocess.run(
            ["python3", "-m", "food_agent.cli.main", "config", "resolve"],
            capture_output=True, text=True, check=True
        )
        ctx = json.loads(res.stdout)
        project_id = ctx.get("project_id")
        if not project_id:
            return None, "Project ID not found in deploy context."

        # 2. Get service URL via gcloud
        res_svc = subprocess.run(
            ["gcloud", "run", "services", "describe", "food-agent-mcp", 
             "--project", project_id, "--region", "us-central1", "--format=value(status.url)"],
            capture_output=True, text=True
        )
        if res_svc.returncode != 0:
            return None, f"Failed to find food-agent-mcp service in {project_id}."
        
        url = res_svc.stdout.strip()
        return {"project_id": project_id, "url": url}, None
    except Exception as e:
        return None, str(e)

def get_tester_pat(project_id):
    """Ensure test@example.com is registered and get its PAT."""
    tester_email = "test@example.com"
    
    # 1. Check if user already has a PAT in our local context or via list
    # (Since list masks it, we only know if they EXIST)
    res_list = subprocess.run(
        ["python3", "-m", "food_agent.cli.main", "admin", "list", "--email-filter", tester_email],
        capture_output=True, text=True, check=True
    )
    users = json.loads(res_list.stdout)
    
    # 2. If missing, register and return the new PAT
    if not users:
        res_reg = subprocess.run(
            ["python3", "-m", "food_agent.cli.main", "admin", "register", tester_email, "--show-token"],
            capture_output=True, text=True, check=True
        )
        user_data = json.loads(res_reg.stdout)
        return user_data["pat"]
    
    # 3. If they exist, we'll try to find a PAT in the environment or just rotate it 
    # for simplicity in this smoke test, BUT we should really just have a known PAT 
    # for automation. For now, I'll rotate it only once.
    # To stop the bloat, I will use a hardcoded PAT if possible or just one rotation.
    
    # Actually, let's just use the FIRST one from the list if it wasn't masked, 
    # but it IS masked. So we must register to get a fresh one.
    # To fix the 'bloat', we need the ADMIN API to support REPLACING instead of APPENDING.
    res_reg = subprocess.run(
        ["python3", "-m", "food_agent.cli.main", "admin", "register", tester_email, "--show-token"],
        capture_output=True, text=True, check=True
    )
    user_data = json.loads(res_reg.stdout)
    return user_data["pat"]

# --- The Test ---

def test_user_journey_smoke():
    """End-to-end smoke test against the live cloud deployment."""
    config, error = get_mcp_config()
    if error:
        pytest.skip(f"Cloud testing environment not ready: {error}")

    project_id = config["project_id"]
    mcp_url = config["url"]
    pat = get_tester_pat(project_id)
    
    # Ensure URL has trailing slash if we're using root path
    if not mcp_url.endswith("/"):
        mcp_url += "/"

    headers = {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # 1. Log two food entries
    today = date.today().isoformat()
    food_entries = [
        {
            "food_name": "Cloud Apple",
            "user_description": "one apple",
            "standard_serving": {"size": {"amount": 1, "unit": "apple"}, "nutrition": {"calories": 95, "protein": 0.5, "carbs": 25, "fat": 0.3}},
            "consumed": {"size": {"amount": 1, "unit": "apple"}, "standard_servings": 1, "nutrition": {"calories": 95, "protein": 0.5, "carbs": 25, "fat": 0.3}, "verified_calculation": True},
            "confidence_score": 10
        },
        {
            "food_name": "Cloud Coffee",
            "user_description": "black coffee",
            "standard_serving": {"size": {"amount": 8, "unit": "oz"}, "nutrition": {"calories": 2, "protein": 0.3, "carbs": 0, "fat": 0}},
            "consumed": {"size": {"amount": 8, "unit": "oz"}, "standard_servings": 1, "nutrition": {"calories": 2, "protein": 0.3, "carbs": 0, "fat": 0}, "verified_calculation": True},
            "confidence_score": 10
        }
    ]

    log_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "log_meal",
            "arguments": {
                "food_entries": food_entries,
                "entry_date": today
            }
        }
    }

    res_log = requests.post(mcp_url, headers=headers, json=log_payload, timeout=20)
    assert res_log.status_code == 200, f"Logging failed: {res_log.text}"
    assert res_log.json()["result"]["isError"] is False

    # 2. Retrieve and verify
    get_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "get_food_log",
            "arguments": {"entry_date": today}
        }
    }

    res_get = requests.post(mcp_url, headers=headers, json=get_payload, timeout=20)
    assert res_get.status_code == 200, f"Retrieval failed: {res_get.text}"
    
    result = res_get.json()["result"]
    # FastMCP structure check
    if "structuredContent" in result:
        items = result["structuredContent"]["items"]
    else:
        # Fallback to parsing text content if needed
        items_json = json.loads(result["content"][0]["text"])
        items = items_json["items"]

    # Verify both items exist
    food_names = [i["food_name"] for i in items]
    assert "Cloud Apple" in food_names
    assert "Cloud Coffee" in food_names
    print(f"\nCloud Smoke Test PASSED against {mcp_url}")
