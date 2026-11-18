# No mock provider: this file is loaded only by the opt-in cloud workflow.
run "aws_accepts_runtime_constraints" {
  command = apply
  assert {
    condition     = alltrue([for name in output.bucket_names : length(name) <= 63 && startswith(name, "kit-")])
    error_message = "AWS must accept distinct bucket names for a 32-character project in staging."
  }
  assert {
    condition     = output.retention_days == 1096
    error_message = "The live CloudWatch log group must retain logs for exactly 1096 days."
  }
  assert {
    condition     = !contains(keys(output.lambda_environment), "AWS_REGION") && output.lambda_environment["ENVIRONMENT"] == "staging"
    error_message = "AWS must create the Lambda without a reserved AWS_REGION variable."
  }
}
