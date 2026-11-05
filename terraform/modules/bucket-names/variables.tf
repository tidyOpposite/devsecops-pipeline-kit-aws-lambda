variable "account_id" {
  description = "AWS account ID included in each bucket's identity."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must contain exactly 12 digits."
  }
}

variable "name_prefix" {
  description = "Environment-aware prefix used to derive stable bucket names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.name_prefix))
    error_message = "name_prefix must start with a lowercase letter and contain only lowercase letters, digits, and hyphens."
  }
}
