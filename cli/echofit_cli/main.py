import click
import sys
import json
import subprocess
import os
import requests
import yaml
from pathlib import Path
from urllib.parse import urlencode
from rich.console import Console
from rich.table import Table
from food_agent.cli import cloud as cloud_util
from food_agent.sdk.config import get_app_config_dir

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
@click.option("--bucket", help="Explicit Storage Bucket Name")
@click.option("--label-value", default="default", help="Label value to search for (default: default)")
@click.option("--overwrite", type=click.Choice(["prompt", "force", "fail"]), default="prompt",
              help="Behavior when config exists: prompt (default), force, or fail")
def config_init(project_id, bucket, label_value, overwrite):
    """Initialize deployment context (Project & Bucket)."""
    # Check for existing config
    config_path = get_app_config_dir() / "admin.yaml"
    if config_path.exists():
        try:
            existing = cloud_util.load_admin_config()
            if overwrite == "fail":
                click.echo(f"Error: Config already exists at {config_path}. Use --overwrite=force to replace.", err=True)
                sys.exit(1)
            elif overwrite == "prompt":
                click.echo(f"Existing configuration found at {config_path}:", err=True)
                click.echo(f"  project_id: {existing.get('project_id')}", err=True)
                click.echo(f"  bucket_name: {existing.get('bucket_name')}", err=True)
                click.echo(f"  gcloud_user: {existing.get('gcloud_user')}", err=True)
                if not click.confirm("Overwrite?"):
                    click.echo("Aborted.", err=True)
                    sys.exit(1)
        except Exception:
            pass  # Config file exists but couldn't be read, proceed with init

    current_user = cloud_util.get_current_gcloud_user()
    if not current_user:
        click.echo("Error: No active gcloud user found. Run 'gcloud auth login'.", err=True)
        sys.exit(1)

    # 1. Project
    if not project_id:
        click.echo(f"Discovering project (label: ai-food-log={label_value})...", err=True)
        try:
            project_id = cloud_util.lookup_project_by_label(label_value=label_value, user_email=current_user)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if not project_id:
        project_id = click.prompt("No project found. Enter Project ID")

    # 2. Bucket
    if not bucket:
        click.echo(f"Discovering bucket (label: ai-food-log={label_value})...", err=True)
        try:
            bucket = cloud_util.lookup_bucket_by_label(label_value=label_value, project_id=project_id)
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
    path = cloud_util.save_admin_config(data)
    click.echo(f"Configuration saved to {path}", err=True)
    click.echo(json.dumps(data))

@config.command("resolve")
def config_resolve():
    """Resolve configuration for Terraform (JSON output)."""
    current_user =cloud_util.get_current_gcloud_user()
    try:
        data =cloud_util.load_admin_config()
        
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
    """Administrative operations (requires gcloud + admin service access)."""
    pass

@admin.group()
def users():
    """Manage users and tokens on the remote service."""
    pass

def get_admin_config():
    """Fetch Admin URL and Shared Secret from Cloud Run."""
    try:
        ctx =cloud_util.load_admin_config()
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

@users.command("add")
@click.argument("email")
@click.option("--pat", help="Optional specific PAT to set")
@click.option("--show-token", is_flag=True, help="Include the real PAT in output")
def users_add(email, pat, show_token):
    """Add a new user and generate a PAT."""
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

@users.command("list")
@click.option("--email-filter", help="Filter by email substring")
@click.option("--limit", default=50, show_default=True, help="Max results")
def users_list(email_filter, limit):
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

@users.command("show")
@click.argument("email")
@click.option("--show-token", is_flag=True, help="Reveal the real PAT in output")
def users_show(email, show_token):
    """Show details for a user."""
    url, secret, oidc = get_admin_config()
    headers = {"Authorization": f"Bearer {oidc}", "X-Admin-Secret": secret}

    r = requests.get(f"{url}/admin/users/{email}", headers=headers, params={"show_token": show_token})
    if r.status_code != 200:
        click.echo(f"Error {r.status_code}: {r.text}", err=True)
        sys.exit(1)

    click.echo(json.dumps(r.json(), indent=2))

@users.command("export")
@click.argument("email")
def users_export(email):
    """Export user config (url + PAT) as YAML for handoff to end user."""
    # 1. Get MCP service URL from Cloud Run
    try:
        ctx = cloud_util.load_admin_config()
        pid = ctx["project_id"]
        res = subprocess.run(
            ["gcloud", "run", "services", "describe", "food-agent-mcp", "--project", pid, "--format=value(status.url)", "--region", "us-central1"],
            capture_output=True, text=True, check=True
        )
        mcp_url = res.stdout.strip().rstrip('/') + '/'
    except Exception as e:
        click.echo(f"Error discovering MCP URL: {e}", err=True)
        sys.exit(1)

    # 2. Get user's PAT via admin service
    url, secret, oidc = get_admin_config()
    headers = {"Authorization": f"Bearer {oidc}", "X-Admin-Secret": secret}
    r = requests.get(f"{url}/admin/users/{email}", headers=headers, params={"show_token": True})
    if r.status_code != 200:
        click.echo(f"Error {r.status_code}: {r.text}", err=True)
        sys.exit(1)

    user_data = r.json()
    pat = user_data.get("pat")
    if not pat:
        click.echo("Error: Could not retrieve PAT. Try 'admin users add' to rotate.", err=True)
        sys.exit(1)

    # 3. Output YAML to stdout
    export_data = {"url": mcp_url, "pat": pat}
    click.echo(yaml.dump(export_data, default_flow_style=False))

# --- User Group (Local Config) ---

def get_user_config_path() -> Path:
    """Get path to local user config file."""
    return get_app_config_dir() / "user.yaml"

def load_user_config() -> dict:
    """Load local user configuration."""
    path = get_user_config_path()
    if path.exists():
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_user_config(data: dict):
    """Save local user configuration."""
    path = get_user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)

@cli.group()
def user():
    """Local user operations (no admin access required)."""
    pass

@user.command("set")
@click.option("--url", required=True, help="MCP service URL")
@click.option("--pat", required=True, help="Personal Access Token")
def user_set(url, pat):
    """Configure local user credentials."""
    data = load_user_config()
    data["url"] = url.rstrip("/") + "/"
    data["pat"] = pat
    save_user_config(data)
    click.echo(f"Saved to {get_user_config_path()}")

@user.command("show")
@click.option("--format", "output_format", type=click.Choice(["rich", "json"]), default="rich",
              help="Output format: rich (default) or json")
def user_show(output_format):
    """Show current local user configuration."""
    data = load_user_config()
    if not data:
        click.echo("No user configured. Run 'food-agent user set' or 'food-agent user import'", err=True)
        sys.exit(1)

    url = data.get("url", "")
    pat = data.get("pat", "")

    # Build full URL with token query string
    base_url = url.rstrip("/")
    url_with_token = f"{base_url}/?token={pat}" if pat else base_url

    if output_format == "json":
        output = {
            "url": url,
            "pat_preview": pat[:8] + "..." if len(pat) > 8 else "***",
            "url_with_token": url_with_token,
            "config_path": str(get_user_config_path())
        }
        click.echo(json.dumps(output, indent=2))
    else:
        console = Console()
        table = Table(title="Food Agent User Configuration", show_header=False, box=None)
        table.add_column("Key", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")

        table.add_row("Config Path", str(get_user_config_path()))
        table.add_row("Service URL", url)
        table.add_row("PAT Preview", pat[:8] + "..." if len(pat) > 8 else "***")
        table.add_row("", "")
        table.add_row("URL-only Auth", url_with_token)

        console.print(table)
        console.print("\n[dim]Use URL-only Auth for clients that don't support headers (Claude.ai, etc.)[/dim]")

@user.command("import")
@click.option("--overwrite", type=click.Choice(["prompt", "force", "fail"]), default="prompt",
              help="Behavior when config exists: prompt (default), force, or fail")
def user_import(overwrite):
    """Import user config from stdin (YAML with url + pat)."""
    # Read YAML from stdin
    try:
        input_data = yaml.safe_load(sys.stdin)
    except Exception as e:
        click.echo(f"Error parsing YAML from stdin: {e}", err=True)
        sys.exit(1)

    if not input_data or not input_data.get("url") or not input_data.get("pat"):
        click.echo("Error: Input must contain 'url' and 'pat' fields.", err=True)
        sys.exit(1)

    new_data = {
        "url": input_data["url"].rstrip("/") + "/",
        "pat": input_data["pat"]
    }

    # Check existing config
    existing = load_user_config()
    if existing:
        differs = existing.get("url") != new_data["url"] or existing.get("pat") != new_data["pat"]
        if differs:
            if overwrite == "fail":
                click.echo("Error: Config already exists and differs. Use --overwrite=force to replace.", err=True)
                sys.exit(1)
            elif overwrite == "prompt":
                click.echo("Existing configuration:", err=True)
                click.echo(f"  url: {existing.get('url')}", err=True)
                click.echo(f"  pat: {existing.get('pat', '')[:8]}...", err=True)
                click.echo("New configuration:", err=True)
                click.echo(f"  url: {new_data['url']}", err=True)
                click.echo(f"  pat: {new_data['pat'][:8]}...", err=True)
                if not click.confirm("Overwrite?"):
                    click.echo("Aborted.", err=True)
                    sys.exit(1)

    save_user_config(new_data)
    click.echo(f"Imported to {get_user_config_path()}")

@user.group()
def log():
    """Food log operations."""
    pass

@log.command("show")
@click.argument("date", required=False)
def log_show(date):
    """Show food log for a date (default: today)."""
    config = load_user_config()
    if not config.get("url") or not config.get("pat"):
        click.echo("No user configured. Run 'food-agent user set --url <url> --pat <pat>'", err=True)
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {config['pat']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,
        "params": {
            "name": "get_food_log",
            "arguments": {"entry_date": date} if date else {}
        }
    }
    r = requests.post(config["url"], json=payload, headers=headers)
    if r.status_code != 200:
        click.echo(f"Error {r.status_code}: {r.text}", err=True)
        sys.exit(1)

    result = r.json()
    if "error" in result:
        click.echo(f"Error: {result['error']}", err=True)
        sys.exit(1)

    click.echo(json.dumps(result.get("result", {}), indent=2))

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
            ctx =cloud_util.load_admin_config()
            project_id = ctx["project_id"]
        except Exception:
            click.echo("Error: Not initialized. Run 'food-agent config init'.", err=True)
            sys.exit(1)

    click.echo(f"Deploying to Project: {project_id}", err=True)
    import time
    tag = int(time.time())
    
    # 1.5 Configure Docker for GCR
    click.echo("--- Configuring Docker for GCR ---", err=True)
    run_cmd(["gcloud", "auth", "configure-docker", "gcr.io", "--quiet"])
    
    # 2. Build & Push Admin Service
    admin_tag = f"gcr.io/{project_id}/food-agent-admin:{tag}"
    run_cmd(["docker", "build", "-f", "deploy/admin/Dockerfile", "-t", admin_tag, "-t", f"gcr.io/{project_id}/food-agent-admin:latest", "."])
    run_cmd(["docker", "push", admin_tag])
    run_cmd(["docker", "push", f"gcr.io/{project_id}/food-agent-admin:latest"])

    mcp_tag = f"gcr.io/{project_id}/food-agent-mcp:{tag}"
    run_cmd(["docker", "build", "-f", "deploy/mcp/Dockerfile", "-t", mcp_tag, "-t", f"gcr.io/{project_id}/food-agent-mcp:latest", "."])
    run_cmd(["docker", "push", mcp_tag])
    run_cmd(["docker", "push", f"gcr.io/{project_id}/food-agent-mcp:latest"])

    # Terraform (Infrastructure only)
    tf_dir = Path("deploy/terraform").resolve()
    run_cmd(["terraform", "init"], cwd=tf_dir)
    run_cmd(["terraform", "apply", "-auto-approve"], cwd=tf_dir)

    # Force Service Update with latest image
    click.echo("--- Updating Cloud Run Services ---", err=True)
    run_cmd([
        "gcloud", "run", "services", "update", "food-agent-admin",
        "--image", f"gcr.io/{project_id}/food-agent-admin:latest",
        "--project", project_id, "--region", "us-central1"
    ])
    run_cmd([
        "gcloud", "run", "services", "update", "food-agent-mcp",
        "--image", f"gcr.io/{project_id}/food-agent-mcp:latest",
        "--project", project_id, "--region", "us-central1"
    ])
    click.echo("Deployment Complete.", err=True)

@cli.group()
def cloud():
    """Cloud operations."""
    pass

@cloud.command("set-env")
@click.argument("service")
@click.option("--name", required=True, help="Environment variable name")
@click.option("--value", required=True, help="Environment variable value")
@click.option("--project-id", help="Override Project ID")
@click.option("--region", default="us-central1", help="Cloud Run region")
def cloud_set_env(service, name, value, project_id, region):
    """Update environment variables for a Cloud Run service."""
    if not project_id:
        try:
            ctx = cloud_util.load_admin_config()
            project_id = ctx["project_id"]
        except Exception:
            click.echo("Error: Not initialized. Run 'food-agent config init'.", err=True)
            sys.exit(1)

    cmd = [
        "gcloud", "run", "services", "update", service,
        "--update-env-vars", f"{name}={value}",
        "--project", project_id,
        "--region", region,
        "--quiet"
    ]
    run_cmd(cmd)
    click.echo(f"Updated {name}={value} on {service}.", err=True)

if __name__ == "__main__":
    cli()