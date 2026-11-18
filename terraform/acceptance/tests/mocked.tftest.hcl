# Credential-free rehearsal of the exact fixture and assertions used in AWS.
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/acceptance-fixture" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:us-east-1:123456789012:acceptance-dlq" }
  }
  mock_data "aws_cloudwatch_log_group" {
    defaults = { retention_in_days = 1096 }
  }
  mock_data "aws_lambda_function" {
    defaults = { environment = [{ variables = { ENVIRONMENT = "staging" } }] }
  }
}

variables {
  expected_account_id   = "123456789012"
  production_account_id = "999999999999"
  aws_region            = "us-east-1"
  project_name          = "acceptance-aaaaaaaaaaaaaaaaaaaaa"
  lambda_image_uri      = "123456789012.dkr.ecr.us-east-1.amazonaws.com/fixture@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "rehearse_runtime_acceptance" {
  command = apply
  assert {
    condition     = alltrue([for name in output.bucket_names : length(name) <= 63 && startswith(name, "kit-")])
    error_message = "Fixture must exercise the shortened S3 names at the project length limit."
  }
  assert {
    condition     = output.retention_days == 1096 && !contains(keys(output.lambda_environment), "AWS_REGION")
    error_message = "Fixture readback must verify retention and reserved Lambda variables."
  }
}

run "reject_production_account" {
  command = plan
  variables {
    production_account_id = "123456789012"
  }
  expect_failures = [var.expected_account_id]
}
