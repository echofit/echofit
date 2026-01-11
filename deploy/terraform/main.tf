terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
      version = "~> 6.0"
    }
    external = {
      source = "hashicorp/external"
      version = "2.3.1"
    }
    random = {
      source = "hashicorp/random"
      version = "3.5.1"
    }
  }
}

# Resolve Project & Bucket Context
data "external" "project_info" {
  program = ["python3", "-m", "food_agent.cli.main", "config", "resolve"]
  working_dir = "${path.module}/../../"
}

locals {
  project_id  = data.external.project_info.result.project_id
  bucket_name = data.external.project_info.result.bucket_name != "" ? data.external.project_info.result.bucket_name : "food-agent-data-${data.external.project_info.result.project_id}"
}

provider "google" {
  project = local.project_id
  region  = "us-central1"
  zone    = "us-central1-a"
}

# --- 1. Storage ---

# Create bucket if it doesn't exist (or manage existing if imported)
# We use 'force_destroy' = false to prevent accidental data loss
resource "google_storage_bucket" "data_bucket" {
  name          = local.bucket_name
  location      = "US"
  force_destroy = false
  
  labels = {
    "ai-food-log" = "default"
  }
  
  uniform_bucket_level_access = true
}

# --- 2. Service Accounts ---

resource "google_service_account" "mcp_sa" {
  account_id   = "food-agent-mcp-sa"
  display_name = "Food Agent MCP Service Account"
}

resource "google_service_account" "admin_sa" {
  account_id   = "food-agent-admin-sa"
  display_name = "Food Agent Admin Service Account"
}

# --- 3. IAM Permissions ---

# MCP needs Read access to Users list and Data
resource "google_storage_bucket_iam_member" "mcp_reader" {
  bucket = google_storage_bucket.data_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.mcp_sa.email}"
}

# Admin needs Write access to Users list
resource "google_storage_bucket_iam_member" "admin_writer" {
  bucket = google_storage_bucket.data_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.admin_sa.email}"
}

# Admin also needs to act as a Service Account (standard for Cloud Run identity)
# (Implicitly handled by Cloud Run creation, but good to note)

# --- 4. Cloud Run Services ---

# Shared Cloud Run Configuration
locals {
  common_env = [
    {
      name  = "FOOD_AGENT_DATA"
      value = "/mnt/gcs/data"
    },
    {
      name  = "FOOD_AGENT_CONFIG"
      value = "/mnt/gcs/config"
    },
    {
      name  = "USERS_BUCKET_NAME"
      value = google_storage_bucket.data_bucket.name
    }
  ]
  
  # GCS FUSE Volume
  volume_mounts = [
    {
      name       = "gcs-data"
      mount_path = "/mnt/gcs"
    }
  ]
}

# Shared Secret Generation
resource "random_password" "admin_secret" {
  length           = 32
  special          = true
  override_special = "_%@"
}

# Service: MCP (Public)
resource "google_cloud_run_v2_service" "mcp_service" {
  name     = "food-agent-mcp"
  location = "us-central1"
  ingress = "INGRESS_TRAFFIC_ALL" # Public
  deletion_protection = false

  template {
    service_account = google_service_account.mcp_sa.email
    
    containers {
      image = "gcr.io/${local.project_id}/food-agent-mcp:latest"
      
      env {
        name  = "MCP_AUTH_TOKEN" # Fallback if we use shared secret locally
        value = "placeholder-replaced-by-users-csv-logic" 
      }
      
      # Inject shared env vars
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      volume_mounts {
        name       = "gcs-data"
        mount_path = "/mnt/gcs"
      }
    }
    
    volumes {
      name = "gcs-data"
      gcs {
        bucket = google_storage_bucket.data_bucket.name
      }
    }
  }
}

# Allow unauthenticated access to MCP (Auth handled by app middleware)
resource "google_cloud_run_service_iam_member" "mcp_public" {
  location = google_cloud_run_v2_service.mcp_service.location
  service  = google_cloud_run_v2_service.mcp_service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Service: Admin (Private)
resource "google_cloud_run_v2_service" "admin_service" {
  name     = "food-agent-admin"
  location = "us-central1"
  ingress = "INGRESS_TRAFFIC_ALL" # Accessible via URL but Auth required
  deletion_protection = false

  template {
    service_account = google_service_account.admin_sa.email
    
    containers {
      image = "gcr.io/${local.project_id}/food-agent-admin:latest"
      
      env {
        name  = "ADMIN_SHARED_SECRET"
        value = random_password.admin_secret.result
      }
      
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      volume_mounts {
        name       = "gcs-data"
        mount_path = "/mnt/gcs"
      }
    }
    
    volumes {
      name = "gcs-data"
      gcs {
        bucket = google_storage_bucket.data_bucket.name
      }
    }
  }
}

# Admin Service Access: Only authenticated Google Users (e.g. You)
# NOTE: You must have the role 'run.invoker' on this service.
# We don't bind 'allUsers' here.

output "mcp_url" {
  value = google_cloud_run_v2_service.mcp_service.uri
}

output "admin_url" {
  value = google_cloud_run_v2_service.admin_service.uri
}