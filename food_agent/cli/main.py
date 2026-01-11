import click
import sys
import json
import subprocess
import os
import requests
from pathlib import Path
from food_agent.cli import cloud

@click.group()
def cli():
    """Food Agent Control Plane."""
    pass

# --- Config Group ---

@cli.group()
def config():
    """Manage deployment configuration."""
    pass

@config.command("init")
@click.option("--project-id", help="Explicit Google Cloud Project ID")
@click.option("--bucket", help="Explicit GCS Bucket Name")
@click.option("--label-value", default="default", help="Label value to search for (default: default)")
def config_init(project_id, bucket, label_value):
    """Initialize deployment context (Project & Bucket)."""
    current_user = cloud.get_current_gcloud_user()
    if not current_user:
        click.echo("Error: No active gcloud user found. Run 'gcloud auth login'.", err=True)
        sys.exit(1)

    # 1. Project
    if not project_id:
        click.echo(f"Discovering project (label: ai-food-log={label_value})...", err=True)
        try:
            project_id = cloud.lookup_project_by_label(label_value=label_value, user_email=current_user)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if not project_id:
        project_id = click.prompt("No project found. Enter Project ID")

    # 2. Bucket
    if not bucket:
        click.echo(f"Discovering bucket (label: ai-food-log={label_value})...", err=True)
        try:
            bucket = cloud.lookup_bucket_by_label(label_value=label_value, project_id=project_id)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if not bucket:
        bucket = click.prompt("No bucket found. Enter Bucket Name", default="", show_default=False)

    # 3. Save
    data = {
        "gcloud_user": current_user,
        "project_id": project_id,
        "bucket_name": bucket,
        "label_value": label_value
    }
    path = cloud.save_deploy_context(data)
    click.echo(f"Configuration saved to {path}", err=True)
    click.echo(json.dumps(data))

@config.command("resolve")
def config_resolve():
    """Resolve configuration for Terraform (JSON output)."""
    current_user = cloud.get_current_gcloud_user()
    try:
        data = cloud.load_deploy_context()
        
        if data.get("gcloud_user") != current_user:
            click.echo(f"Error: Configuration mismatch. Configured for '{data.get('gcloud_user')}' but current user is '{current_user}'.", err=True)
            sys.exit(1)
            
        click.echo(json.dumps({
            "project_id": data.get("project_id"),
            "bucket_name": data.get("bucket_name")
        }))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

# --- Admin Group ---

@cli.group()
def admin():
    """Administer the remote agent (Users/Tokens)."""
    pass

def get_admin_config():
    """Fetch Admin URL and Shared Secret from Cloud Run."""
    try:
        ctx = cloud.load_deploy_context()
        pid = ctx["project_id"]
        
        # Get full service description as JSON
        res = subprocess.run(
            ["gcloud", "run", "services", "describe", "food-agent-admin", "--project", pid, "--format=json", "--region", "us-central1"],
            capture_output=True, text=True, check=True
        )
        service_data = json.loads(res.stdout)
        
        # 1. Get URL
        url = service_data.get("status", {}).get("url")
        
        # 2. Get Secret from env vars
        secret = None
        # Try both v1 and v2 structures
        containers = service_data.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        if not containers:
            containers = service_data.get("template", {}).get("containers", [])
            
        for container in containers:
            for env_var in container.get("env", []):
                if env_var.get("name") == "ADMIN_SHARED_SECRET":
                    secret = env_var.get("value")
                    break
        
        if not secret:
            raise RuntimeError("ADMIN_SHARED_SECRET not found in service configuration.")
        
        # 3. Get OIDC Token
        res_token = subprocess.run(["gcloud", "auth", "print-identity-token"], capture_output=True, text=True, check=True)
        oidc_token = res_token.stdout.strip()
        
        return url, secret, oidc_token
    except Exception as e:
        click.echo(f"Error resolving admin config: {e}", err=True)
        sys.exit(1)

@admin.command("register")
@click.argument("email")
@click.option("--pat", help="Optional specific PAT to set")
@click.option("--show-token", is_flag=True, help="Include the real PAT in output")
def admin_register(email, pat, show_token):
    """Register a new user and generate a PAT."""
    url, secret, oidc = get_admin_config()
    headers = {
        "Authorization": f"Bearer {oidc}",
        "X-Admin-Secret": secret,
        "Content-Type": "application/json"
    }
    payload = {"email": email}
    if pat:
        payload["pat"] = pat
        
    r = requests.post(f"{url}/admin/users", json=payload, headers=headers, params={"show_token": show_token})
    if r.status_code != 200:
        click.echo(f"Error {r.status_code}: {r.text}", err=True)
        sys.exit(1)
        
    click.echo(json.dumps(r.json(), indent=2))

@admin.command("list")
@click.option("--email-filter", help="Filter by email substring")
@click.option("--limit", default=50, show_default=True, help="Max results")
def admin_list(email_filter, limit):
    """List registered users (tokens always masked)."""
    url, secret, oidc = get_admin_config()
    headers = {"Authorization": f"Bearer {oidc}", "X-Admin-Secret": secret}
    params = {"limit": limit}
    if email_filter:
        params["email_filter"] = email_filter
        
    r = requests.get(f"{url}/admin/users", headers=headers, params=params)
    if r.status_code != 200:
        click.echo(f"Error {r.status_code}: {r.text}", err=True)
        sys.exit(1)
        
    click.echo(json.dumps(r.json(), indent=2))

@admin.command("show")
@click.argument("email")
@click.option("--show-token", is_flag=True, help="Reveal the real PAT (NOT SUPPORTED BY API - will fail or mask)")
def admin_show(email, show_token):
    """Show details for a user. Note: Token is always masked by Server API."""
    url, secret, oidc = get_admin_config()
    headers = {"Authorization": f"Bearer {oidc}", "X-Admin-Secret": secret}
    
    r = requests.get(f"{url}/admin/users/{email}", headers=headers)
    if r.status_code != 200:
        click.echo(f"Error {r.status_code}: {r.text}", err=True)
        sys.exit(1)
        
    data = r.json()
    if show_token:
        click.echo("Warning: Server API does not expose tokens on lookup for security. Use 'register' to rotate/view.", err=True)
        
    click.echo(json.dumps(data, indent=2))

# --- Deployment ---

def run_cmd(cmd, env=None, cwd=None):
    """Run a shell command and stream output."""
    click.echo(f"Running: {' '.join(cmd)}", err=True)
    try:
        subprocess.run(cmd, check=True, env=env, cwd=cwd)
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: Command failed with code {e.returncode}", err=True)
        sys.exit(e.returncode)

@cli.command()
@click.option("--project-id", help="Override Project ID")
def deploy(project_id):
    """Deploy the agent to Google Cloud."""
    if not project_id:
        try:
            ctx = cloud.load_deploy_context()
            project_id = ctx["project_id"]
        except Exception:
            click.echo("Error: Not initialized. Run 'food-agent config init'.", err=True)
            sys.exit(1)

    click.echo(f"Deploying to Project: {project_id}", err=True)
    
    # 1.5 Configure Docker for GCR
    click.echo("--- Configuring Docker for GCR ---", err=True)
    run_cmd(["gcloud", "auth", "configure-docker", "gcr.io", "--quiet"])
    
    # 2. Build & Push Admin Service
    admin_tag = f"gcr.io/{project_id}/food-agent-admin:latest"
    run_cmd(["docker", "build", "-f", "deploy/admin/Dockerfile", "-t", admin_tag, "."])
    run_cmd(["docker", "push", admin_tag])

    mcp_tag = f"gcr.io/{project_id}/food-agent-mcp:latest"
    run_cmd(["docker", "build", "-f", "deploy/mcp/Dockerfile", "-t", mcp_tag, "."])
    run_cmd(["docker", "push", mcp_tag])

    # Terraform
    tf_dir = Path("deploy/terraform").resolve()
    run_cmd(["terraform", "init"], cwd=tf_dir)
    run_cmd(["terraform", "apply", "-auto-approve"], cwd=tf_dir)
    click.echo("Deployment Complete.", err=True)

if __name__ == "__main__":
    cli()