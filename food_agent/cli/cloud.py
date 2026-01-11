import os
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from food_agent.sdk.config import get_app_config_dir

def get_current_gcloud_user() -> Optional[str]:
    """Get the active gcloud account email."""
    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "account"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def lookup_project_by_label(label_key: str = "ai-food-log", label_value: str = "default", user_email: Optional[str] = None) -> Optional[str]:
    """Query GCP for a project with the specific label. Enforces exactly one match."""
    try:
        result = subprocess.run(
            ["gcloud", "projects", "list", f"--filter=labels.{label_key}={label_value}", "--format=value(projectId)"],
            capture_output=True,
            text=True,
            check=True
        )
        ids = result.stdout.strip().splitlines()
        if len(ids) > 1:
            raise RuntimeError(f"Multiple projects found with label '{label_key}={label_value}': {ids}")
        return ids[0] if ids else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def lookup_bucket_by_label(label_key: str = "ai-food-log", label_value: str = "default", project_id: Optional[str] = None) -> Optional[str]:
    """Query GCP for a storage bucket with the specific label. Enforces exactly one match."""
    try:
        cmd = ["gcloud", "storage", "buckets", "list", f"--filter=labels.{label_key}={label_value}", "--format=value(name)"]
        if project_id:
            cmd.extend(["--project", project_id])
            
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        names = result.stdout.strip().splitlines()
        if len(names) > 1:
            raise RuntimeError(f"Multiple buckets found with label '{label_key}={label_value}': {names}")
        return names[0] if names else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def save_deploy_context(data: Dict[str, Any]):
    """Save the deployment context to disk."""
    config_dir = get_app_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    context_file = config_dir / "deploy_context.json"
    
    with open(context_file, "w") as f:
        json.dump(data, f, indent=2)
    return context_file

def load_deploy_context() -> Dict[str, Any]:
    """Load the deployment context from disk."""
    config_dir = get_app_config_dir()
    context_file = config_dir / "deploy_context.json"
    
    if not context_file.exists():
        raise FileNotFoundError("Deployment context not initialized.")
        
    with open(context_file, "r") as f:
        return json.load(f)