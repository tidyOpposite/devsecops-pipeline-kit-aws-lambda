mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { name = "us-east-1" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111" }
  }
}

variables {
  lambda_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/example@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "production_root_rejects_shared_pool" {
  command = plan
  variables {
    lambda_reserved_concurrent_executions = -1
  }
  expect_failures = [var.lambda_reserved_concurrent_executions]
}

run "production_root_rejects_disabled_function" {
  command = plan
  variables {
    lambda_reserved_concurrent_executions = 0
  }
  expect_failures = [var.lambda_reserved_concurrent_executions]
}

run "production_root_rejects_fractional_reservation" {
  command = plan
  variables {
    lambda_reserved_concurrent_executions = 1.5
  }
  expect_failures = [var.lambda_reserved_concurrent_executions]
}
