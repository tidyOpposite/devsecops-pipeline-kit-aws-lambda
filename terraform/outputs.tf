output "environment" {
  description = "Active deployment environment resolved from the Terraform workspace."
  value       = local.environment
}

output "terraform_workspace" {
  description = "Terraform workspace backing this environment."
  value       = terraform.workspace
}

output "api_gateway_health_url" {
  description = "Health endpoint used by CI smoke tests and DAST readiness checks."
  value       = module.api_gateway.health_url
}

output "api_gateway_invoke_url" {
  description = "Base URL for invoking the API Gateway default stage."
  value       = module.api_gateway.invoke_url
}

output "api_gateway_authorization_type" {
  description = "Authorization type configured for API Gateway routes."
  value       = var.api_authorization_type
}

output "ecr_repository_name" {
  description = "Name of the ECR repository for Lambda images."
  value       = module.ecr.repository_name
}

output "ecr_repository_url" {
  description = "URL of the ECR repository for Lambda images."
  value       = module.ecr.repository_url
}

output "kms_key_arn" {
  description = "ARN of the customer-managed KMS key used by workload resources."
  value       = module.kms.key_arn
}

output "lambda_current_image_uri" {
  description = "Image URI currently configured on the Lambda function."
  value       = module.lambda.image_uri
}

output "lambda_dlq_sqs_url" {
  description = "URL of the SQS dead-letter queue configured for Lambda."
  value       = module.lambda.dlq_url
}

output "lambda_function_name" {
  description = "Name of the deployed Lambda function."
  value       = module.lambda.function_name
}

output "log_s3_bucket_name" {
  description = "Name of the S3 bucket receiving access logs."
  value       = module.storage.log_bucket_name
}

output "output_s3_bucket_name" {
  description = "Name of the private S3 bucket for workload data."
  value       = module.storage.output_bucket_name
}
