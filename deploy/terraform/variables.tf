variable "admin_secret" {
  description = "Shared secret for Admin Service authentication"
  type        = string
  sensitive   = true
  default     = "changeme_if_not_set_via_env"
}
