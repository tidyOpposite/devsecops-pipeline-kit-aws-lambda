output "dlq_arn" {
  description = "ARN of the Lambda dead-letter queue."
  value       = aws_sqs_queue.lambda_dlq.arn
}

output "dlq_url" {
  description = "URL of the Lambda dead-letter queue."
  value       = aws_sqs_queue.lambda_dlq.id
}

output "function_arn" {
  description = "ARN of the Lambda function."
  value       = aws_lambda_function.workload.arn
}

output "function_name" {
  description = "Name of the Lambda function."
  value       = aws_lambda_function.workload.function_name
}

output "image_uri" {
  description = "Image URI currently configured for Lambda."
  value       = aws_lambda_function.workload.image_uri
}

output "invoke_arn" {
  description = "Invoke ARN used by API Gateway integration."
  value       = aws_lambda_function.workload.invoke_arn
}

output "role_arn" {
  description = "ARN of the Lambda execution role."
  value       = aws_iam_role.lambda_exec_role.arn
}

output "reserved_concurrency" {
  description = "Actual function reservation; -1 uses the shared account pool."
  value       = aws_lambda_function.workload.reserved_concurrent_executions
}
