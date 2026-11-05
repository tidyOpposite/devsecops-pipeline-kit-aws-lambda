variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key used by Lambda-adjacent resources."
  type        = string
}

variable "lambda_image_uri" {
  description = "Immutable ECR image URI for the Lambda function."
  type        = string

  validation {
    condition = var.lambda_image_uri == "" || (
      can(regex("^\\d{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/.+(?::[^:@]+|@sha256:[A-Fa-f0-9]{64})$", var.lambda_image_uri))
      && !can(regex(":(latest|bootstrap)$", lower(var.lambda_image_uri)))
    )
    error_message = "lambda_image_uri must be empty for validation-only runs or an immutable ECR image URI; latest/bootstrap tags are not allowed."
  }
}

variable "lambda_memory_size" {
  description = "Lambda memory size in MB."
  type        = number
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds."
  type        = number
}

variable "reserved_concurrent_executions" {
  description = "Function-level reserved concurrency limit."
  type        = number
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

variable "output_bucket_arn" {
  description = "ARN of the private workload data bucket."
  type        = string
}

variable "output_bucket_name" {
  description = "Name of the private workload data bucket."
  type        = string
}

variable "tags" {
  description = "Common tags applied to module resources."
  type        = map(string)
}
