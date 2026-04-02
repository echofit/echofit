import os
import json
import subprocess
import sys
import pytest
from pathlib import Path

@pytest.fixture
def staged_data(tmp_path):
    """Setup a temporary data directory with a sample food log."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Create a daily log entry for 2026-01-10
    log_dir = data_dir / "daily"
    log_dir.mkdir()
    log_file = log_dir / "2026-01-10_food-log.json"
    
    sample_entry = {
        "food_name": "Stdio Test Apple",
        "consumed": {
            "nutrition": {
                "calories": 95,
                "protein": 0.5,
                "carbs": 25,
                "fat": 0.3
            }
        }
    }
    log_file.write_text(json.dumps([sample_entry]))
    
    return data_dir

def test_mcp_stdio_get_food_log(staged_data):
    """Test the stdio server's ability to retrieve a log entry via JSON-RPC."""
    # Setup environment
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    env["ECHOFIT_DATA"] = str(staged_data)
    
    # Start the server process
    process = subprocess.Popen(
        [sys.executable, "-m", "mcp_app", "--config", "mcp-app.yaml"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    
    try:
        # 1. Handshake: initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest-client", "version": "1.0.0"}
            }
        }
        process.stdin.write(json.dumps(init_req) + "\n")
        process.stdin.flush()
        
        # Read initialization response
        init_res = json.loads(process.stdout.readline())
        assert init_res["id"] == 1
        assert "capabilities" in init_res["result"]

        # 2. Tool Call: get_food_log
        call_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_food_log",
                "arguments": {"entry_date": "2026-01-10"}
            }
        }
        process.stdin.write(json.dumps(call_req) + "\n")
        process.stdin.flush()
        
        # Read tool response
        # FastMCP might output INFO logs to stdout if not configured carefully, 
        # but standard behavior should be JSON per line.
        # We skip any non-JSON lines (like FastMCP startup logs if they bleed over)
        while True:
            line = process.stdout.readline()
            if not line:
                pytest.fail("Server closed before tool response")
            try:
                call_res = json.loads(line)
                if call_res.get("id") == 2:
                    break
            except json.JSONDecodeError:
                continue

        # 3. Assertions
        assert "result" in call_res
        result = call_res["result"]
        
        # FastMCP wraps the tool return value in 'content' (legacy/text) 
        # or 'structuredContent' (newer) depending on version and config.
        # Our server returns a dict, so we check the result contents.
        content_str = str(result)
        assert "Stdio Test Apple" in content_str
        assert "100" in content_str # Calories rounded (95 -> 100)

    finally:
        process.terminate()
        process.wait(timeout=5)
