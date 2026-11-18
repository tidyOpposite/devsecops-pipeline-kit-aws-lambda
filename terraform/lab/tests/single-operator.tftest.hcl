# No AWS credentials or resources: exercise the same modules as the real lab.
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-north-1:123456789012:key/11111111-1111-1111-1111-111111111111" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/lab-fixture" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:eu-north-1:123456789012:lab-dlq" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = { execution_arn = "arn:aws:execute-api:eu-north-1:123456789012:labfixture" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:eu-north-1:123456789012:log-group:/aws/lambda/labfixture" }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn        = "arn:aws:lambda:eu-north-1:123456789012:function:kit-lab-diploma-abcdef-dev-lambda"
      invoke_arn = "arn:aws:apigateway:eu-north-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-north-1:123456789012:function:kit-lab-diploma-abcdef-dev-lambda/invocations"
    }
  }
}

variables {
  expected_account_id = "123456789012"
  aws_region          = "eu-north-1"
  project_name        = "kit-lab-diploma-abcdef"
  lambda_image_uri    = "123456789012.dkr.ecr.eu-north-1.amazonaws.com/kit-lab-diploma-abcdef-dev-lambda-repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "dev_lab_uses_shared_modules_and_own_scope" {
  command = apply
  assert {
    condition     = output.lab_context.environment == "dev" && output.lab_context.purpose == "SingleOperatorLab" && output.lab_context.account_id == "123456789012"
    error_message = "Single-operator execution must remain explicitly dev-only and account-bound."
  }
  assert {
    condition     = output.lab_context.image_uri == var.lambda_image_uri && output.lab_context.lambda_function_name == "kit-lab-diploma-abcdef-dev-lambda"
    error_message = "Lambda must retain its immutable image and unique lab name."
  }
}

run "reject_non_lab_project" {
  command = plan
  variables {
    project_name = "production"
  }
  expect_failures = [var.project_name]
}

run "registry_can_be_prepared_before_image_publication" {
  command = plan
  plan_options {
    target = [module.kms, module.ecr]
  }
  variables {
    lambda_image_uri = ""
  }
}

run "explicit_shared_pool_mode_retains_the_account_bound_dev_scope" {
  command = apply
  variables {
    reserved_concurrency = -1
  }
  assert {
    condition     = output.lab_context.reserved_concurrency == -1 && output.lab_context.environment == "dev"
    error_message = "Unreserved mode must reach the actual Lambda resource and remain dev-only."
  }
}

run "reject_disabled_function" {
  command = plan
  variables {
    reserved_concurrency = 0
  }
  expect_failures = [var.reserved_concurrency]
}

run "reject_fractional_reservation" {
  command = plan
  variables {
    reserved_concurrency = 1.5
  }
  expect_failures = [var.reserved_concurrency]
}
