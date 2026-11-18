output "backend_config" {
  description = "Values to copy into terraform/backend.tf."
  value = {
    bucket         = aws_s3_bucket.terraform_state.bucket
    dynamodb_table = aws_dynamodb_table.terraform_locks.name
    region         = var.aws_region
  }
}

output "dynamodb_lock_table_name" {
  description = "DynamoDB lock table name."
  value       = aws_dynamodb_table.terraform_locks.name
}

output "state_bucket_name" {
  description = "Terraform state bucket name."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "state_log_bucket_name" {
  description = "Terraform state access log bucket name."
  value       = aws_s3_bucket.terraform_state_logs.bucket
}

output "state_kms_key_arn" {
  description = "KMS key ARN used for Terraform state backend encryption."
  value       = aws_kms_key.terraform_state.arn
}
