# Path Resolution & Configuration Design

## Philosophy
We separate **Machine Configuration** (bootstrap) from **Application Configuration** (shared settings). This allows users to store their actual configuration and data in synced folders (e.g., Dropbox, Git repo) while keeping a lightweight pointer on the local machine.

## Components

### 1. Bootstrap Settings (`settings.json`)
*   **Purpose:** A machine-specific pointer file. It tells the app where the *real* data and config live.
*   **Location Strategy:**
    1.  `FOOD_AGENT_SETTINGS` (Environment Variable)
    2.  `XDG_CONFIG_HOME/food-agent/settings.json` (Default)
*   **Content Schema:**
    ```json
    {
      "paths": {
        "config": "/path/to/synced/config",
        "data": "/path/to/synced/data"
      }
    }
    ```
*   **Backup Policy:** Disposable. Do not sync.

### 2. Application Configuration (`config/`)
*   **Purpose:** Shared behavior settings (e.g., `app.yaml`, `deploy_context.json`).
*   **Location Strategy:**
    1.  `FOOD_AGENT_CONFIG` (Environment Variable)
    2.  Value of `paths.config` in Bootstrap Settings.
    3.  `XDG_CONFIG_HOME/food-agent` (Default)

### 3. Application Data (`data/`)
*   **Purpose:** User content (logs, catalog).
*   **Location Strategy:**
    1.  `FOOD_AGENT_DATA` (Environment Variable)
    2.  Value of `paths.data` in Bootstrap Settings.
    3.  `XDG_DATA_HOME/food-agent` (Default)

## Resolution Logic (Pseudocode)

```python
def get_bootstrap_file():
    if env.FOOD_AGENT_SETTINGS: return env.FOOD_AGENT_SETTINGS
    return "~/.config/food-agent/settings.json"

def get_config_dir():
    if env.FOOD_AGENT_CONFIG: return env.FOOD_AGENT_CONFIG
    
    settings = read_json(get_bootstrap_file())
    if settings.paths.config: return settings.paths.config
    
    return "~/.config/food-agent"

def get_data_dir():
    if env.FOOD_AGENT_DATA: return env.FOOD_AGENT_DATA
    
    settings = read_json(get_bootstrap_file())
    if settings.paths.data: return settings.paths.data
    
    return "~/.local/share/food-agent"
```
