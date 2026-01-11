import os
import json
import time
import subprocess
import requests
import pytest
import sys
import socket
from pathlib import Path

def get_free_port():
    """Find a free port to avoid conflicts."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def test_get_food_log_over_http(tmp_path):
    """
    End-to-End Integration Test:
    1. Setup isolated data dir with users.csv and a log file.
    2. Start the MCP server in a separate process.
    3. Call the tool over HTTP and verify data comes back.
    """
    # 1. Setup Data
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Register user
    users_file = data_dir / "users.csv"
    users_file.write_text("integration-pat,user@example.com\n")
    
    # Create log entry for user user@example.com (sanitized to user_example.com)
    log_dir = data_dir / "user_example.com" / "daily"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "2026-01-10_food-log.json"
    
    dummy_entry = {
        "food_name": "Integration Steak",
        "consumed": {"nutrition": {"calories": 1234, "protein": 100, "carbs": 0, "fat": 50}}
    }
    log_file.write_text(json.dumps([dummy_entry]))

    # 2. Start Server
    port = get_free_port()
    env = os.environ.copy()
    env["FOOD_AGENT_DATA"] = str(data_dir)
    env["PYTHONPATH"] = os.getcwd()
    env["ADMIN_SHARED_SECRET"] = "this_is_a_very_long_secret_32_chars_long"
    env["MCP_ALLOWED_HOSTS"] = "localhost,127.0.0.1"
    
    # We use 'uvicorn' directly in a subprocess
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "food_agent.mcp_service.app:app", 
         "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # 3. Wait for server to be ready
    time.sleep(5)
    
    try:
        # 4. Invoke Handshake + Tool Call
        base_url = f"http://127.0.0.1:{port}"
        headers = {
            "Authorization": "Bearer integration-pat",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # In Stateless HTTP mode (mcp/server.py), the tool call goes directly to root /
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_food_log",
                "arguments": {"entry_date": "2026-01-10"}
            }
        }
        
        response = requests.post(base_url + "/", headers=headers, json=payload, timeout=10)
        
        # 5. Assert Success
        if response.status_code != 200:
            # Print server errors for debugging if test fails
            stdout, stderr = server_process.communicate(timeout=1)
            print(f"Server STDOUT: {stdout}")
            print(f"Server STDERR: {stderr}")
            pytest.fail(f"Request failed with {response.status_code}: {response.text}")

        data = response.json()
        
        # 6. Verify Content
        # We expect the 'Integration Steak' to be present in the structured output
        assert "result" in data
        res = data["result"]
        # FastMCP wraps output in 'content' (list of objects) and 'structuredContent'
        assert "Integration Steak" in str(res)
        
        # Deep check
        found_steak = False
        items = res.get("structuredContent", {}).get("items", [])
        for item in items:
            if item["food_name"] == "Integration Steak":
                assert item["consumed"]["nutrition"]["calories"] == 1230 # rounded
                found_steak = True
                break
        
        assert found_steak, "Steak not found in returned items"
        print("\nIntegration Test PASSED: Actual food data retrieved over HTTP.")

    finally:
        server_process.kill()
        server_process.wait()
