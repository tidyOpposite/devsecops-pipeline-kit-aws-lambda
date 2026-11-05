variable "api_throttling_burst_limit" {
  description = "API Gateway burst throttle limit."
  type        = number
}

variable "api_throttling_rate_limit" {
  description = "API Gateway steady-state throttle limit."
  type        = number
}

variable "authorization_type" {
  description = "API Gateway HTTP route authorization type."
  type        = string
  default     = "AWS_IAM"

  validation {
    condition     = contains(["AWS_IAM", "NONE"], var.authorization_type)
    error_message = "authorization_type must be AWS_IAM or NONE."
  }
}

variable "cors_allowed_origins" {
  description = "Allowed CORS origins."
  type        = list(string)

  validation {
    condition     = length(var.cors_allowed_origins) > 0 && alltrue([for origin in var.cors_allowed_origins : length(trimspace(origin)) > 0])
    error_message = "cors_allowed_origins must contain at least one non-empty origin."
  }
}

variable "kms_key_arn" {
  description = "KMS key used for API Gateway access logs."
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Lambda invoke ARN for API Gateway integration."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention in days."
  type        = number

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be one of the CloudWatch Logs supported retention periods."
  }
}

variable "name_prefix" {
  description = "Environment-aware resource name prefix."
  type        = string
}

variable "tags" {
  description = "Common tags applied to module resources."
  type        = map(string)
}
