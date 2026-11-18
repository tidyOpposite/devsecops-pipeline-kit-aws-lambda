variable "expected_account_id" {
  description = "Optional account guard for reviewed backend bootstrap and decommission operations."
  type        = string
  default     = ""
  validation {
    condition     = var.expected_account_id == "" || can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id must be empty or an independently confirmed 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "AWS region for the Terraform state backend."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for Terraform remote state."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid globally unique S3 bucket name."
  }
}

variable "state_log_bucket_name" {
  description = "Optional globally unique S3 bucket name for Terraform state access logs. Defaults to <state_bucket_name>-logs."
  type        = string
  default     = ""

  validation {
    condition = var.state_log_bucket_name == "" || (
      can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_log_bucket_name))
    )
    error_message = "state_log_bucket_name must be empty or a valid globally unique S3 bucket name."
  }
}

variable "lock_table_name" {
  description = "DynamoDB table name used by the Terraform S3 backend for state locking."
  type        = string
  default     = "devsecops-pipeline-terraform-locks"
}

variable "tags" {
  description = "Tags applied to backend resources."
  type        = map(string)
  default = {
    Project   = "devsecops-pipeline"
    ManagedBy = "Terraform"
    Purpose   = "terraform-state"
  }
}
