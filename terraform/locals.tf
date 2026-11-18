locals {
  supported_environments = ["dev", "staging", "prod"]
  requested_environment  = terraform.workspace == "default" ? var.environment : terraform.workspace
  environment            = contains(local.supported_environments, local.requested_environment) ? local.requested_environment : var.environment
  environment_settings   = var.environment_config[local.environment]
  name_prefix            = "${var.project_name}-${local.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = local.environment
    ManagedBy   = "Terraform"
  }
}

check "supported_workspace" {
  assert {
    condition     = contains(concat(["default"], local.supported_environments), terraform.workspace)
    error_message = "Terraform workspace must be one of: default, dev, staging, prod."
  }
}
