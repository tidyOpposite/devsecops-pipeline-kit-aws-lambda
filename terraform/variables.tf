variable "expected_account_id" {
  description = "Optional account guard for reviewed manual operations, including decommissioning."
  type        = string
  default     = ""
  validation {
    condition     = var.expected_account_id == "" || can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id must be empty or an independently confirmed 12-digit AWS account ID."
  }
}

variable "project_name" {
  description = "Назва проекту (використовується для іменування ресурсів)."
  type        = string
  default     = "devsecops-pipeline"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.project_name))
    error_message = "project_name must be 3-32 chars and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "aws_region" {
  description = "Регіон AWS для розгортання ресурсів."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Fallback environment used when Terraform runs in the default workspace."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "environment_config" {
  description = "Per-environment runtime and API settings. Terraform workspaces select the active environment."
  type = map(object({
    lambda_memory_size         = number
    lambda_timeout             = number
    log_retention_days         = number
    api_throttling_burst_limit = number
    api_throttling_rate_limit  = number
    cors_allowed_origins       = list(string)
  }))

  default = {
    dev = {
      lambda_memory_size         = 1024
      lambda_timeout             = 120
      log_retention_days         = 30
      api_throttling_burst_limit = 25
      api_throttling_rate_limit  = 50
      cors_allowed_origins       = ["*"]
    }
    staging = {
      lambda_memory_size         = 1536
      lambda_timeout             = 180
      log_retention_days         = 90
      api_throttling_burst_limit = 50
      api_throttling_rate_limit  = 100
      cors_allowed_origins       = ["*"]
    }
    prod = {
      lambda_memory_size         = 2048
      lambda_timeout             = 240
      log_retention_days         = 365
      api_throttling_burst_limit = 100
      api_throttling_rate_limit  = 200
      cors_allowed_origins       = ["https://app.example.com"]
    }
  }

  validation {
    condition     = alltrue([for environment in ["dev", "staging", "prod"] : contains(keys(var.environment_config), environment)])
    error_message = "environment_config must define dev, staging, and prod."
  }

  validation {
    condition = alltrue(flatten([
      for _, settings in var.environment_config : [
        settings.lambda_memory_size >= 128 && settings.lambda_memory_size <= 10240,
        settings.lambda_timeout >= 1 && settings.lambda_timeout <= 900,
        settings.api_throttling_burst_limit >= 1 && settings.api_throttling_burst_limit <= 5000,
        settings.api_throttling_rate_limit >= 1 && settings.api_throttling_rate_limit <= 10000,
        length(settings.cors_allowed_origins) > 0,
        alltrue([for origin in settings.cors_allowed_origins : length(trimspace(origin)) > 0])
      ]
    ]))
    error_message = "environment_config values must stay within Lambda/API limits and define at least one non-empty CORS origin per environment."
  }

  validation {
    condition     = alltrue([for settings in values(var.environment_config) : contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], settings.log_retention_days)])
    error_message = "log_retention_days must be one of the CloudWatch Logs supported retention periods."
  }

  validation {
    condition     = !contains(try(var.environment_config["prod"].cors_allowed_origins, []), "*")
    error_message = "environment_config.prod.cors_allowed_origins must not contain wildcard '*'; use explicit production origins."
  }
}

variable "api_authorization_type" {
  description = "Authorization mode for API Gateway HTTP routes. Use AWS_IAM for production workloads; NONE is only for demos or public non-sensitive APIs."
  type        = string
  default     = "AWS_IAM"

  validation {
    condition     = contains(["AWS_IAM", "NONE"], var.api_authorization_type)
    error_message = "api_authorization_type must be AWS_IAM or NONE."
  }
}

variable "lambda_memory_size" {
  description = "Legacy fallback for Lambda memory size. Prefer environment_config."
  type        = number
  default     = 1024
}

variable "lambda_timeout" {
  description = "Legacy fallback for Lambda timeout. Prefer environment_config."
  type        = number
  default     = 120
}

variable "lambda_reserved_concurrent_executions" {
  description = "Function-level reserved concurrency limit for the Lambda workload."
  type        = number
  default     = 10

  validation {
    condition     = var.lambda_reserved_concurrent_executions >= 1 && var.lambda_reserved_concurrent_executions <= 1000 && floor(var.lambda_reserved_concurrent_executions) == var.lambda_reserved_concurrent_executions
    error_message = "lambda_reserved_concurrent_executions must be an integer between 1 and 1000. Shared-pool mode is restricted to the separate dev lab."
  }
}

variable "lambda_image_uri" {
  description = "Full immutable image URI for the Lambda workload."
  type        = string
  default     = ""

  validation {
    condition = var.lambda_image_uri == "" || (
      can(regex("^\\d{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/.+(?::[^:@]+|@sha256:[A-Fa-f0-9]{64})$", var.lambda_image_uri))
      && !can(regex(":(latest|bootstrap)$", lower(var.lambda_image_uri)))
    )
    error_message = "lambda_image_uri must be empty for validation-only runs or an immutable ECR image URI; latest/bootstrap tags are not allowed."
  }
}

variable "terraform_admin_role_name" {
  description = "Optional IAM role name allowed to administer the workload KMS key in addition to account root delegation."
  type        = string
  default     = ""
}
