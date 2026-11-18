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

run "preserve_existing_short_names" {
  command = plan
  variables {
    project_name = "existing-project"
    environment  = "prod"
  }
  plan_options {
    target = [module.storage]
  }
  assert {
    condition = (
      output.log_s3_bucket_name == "existing-project-prod-access-logs-123456789012" &&
      output.output_s3_bucket_name == "existing-project-prod-workload-data-123456789012"
    )
    error_message = "Existing valid bucket names must be preserved."
  }
}

run "preserve_names_at_the_length_limit" {
  command = plan
  variables {
    project_name = "abcdefghijklmnopqrstuvwxyzabcde"
    environment  = "prod"
  }
  plan_options {
    target = [module.storage]
  }
  assert {
    condition = (
      output.log_s3_bucket_name == "abcdefghijklmnopqrstuvwxyzabcde-prod-access-logs-123456789012" &&
      output.output_s3_bucket_name == "abcdefghijklmnopqrstuvwxyzabcde-prod-workload-data-123456789012" &&
      length(output.output_s3_bucket_name) == 63
    )
    error_message = "A valid bucket at the 63-character limit must keep its name."
  }
}

run "shorten_only_the_invalid_bucket" {
  command = plan
  variables {
    project_name = "abcdefghijklmnopqrstuvwxyzabc"
    environment  = "staging"
  }
  plan_options {
    target = [module.storage]
  }
  assert {
    condition = (
      output.log_s3_bucket_name == "abcdefghijklmnopqrstuvwxyzabc-staging-access-logs-123456789012" &&
      length(output.output_s3_bucket_name) == 63 &&
      output.output_s3_bucket_name == "kit-${substr("abcdefghijklmnopqrstuvwxyzabc-staging-workload-data-123456789012", 0, 42)}-${substr(sha256("abcdefghijklmnopqrstuvwxyzabc-staging-workload-data-123456789012"), 0, 16)}"
    )
    error_message = "Shortening a workload bucket must preserve an already valid access-log bucket."
  }
}

run "support_the_longest_project_in_staging" {
  command = plan
  variables {
    project_name = "abcdefghijklmnopqrstuvwxyzabcdef"
    environment  = "staging"
  }
  plan_options {
    target = [module.storage]
  }
  assert {
    condition = (
      length(output.log_s3_bucket_name) <= 63 &&
      length(output.output_s3_bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9-]*[a-z0-9]$", output.log_s3_bucket_name)) &&
      can(regex("^[a-z0-9][a-z0-9-]*[a-z0-9]$", output.output_s3_bucket_name)) &&
      output.log_s3_bucket_name != output.output_s3_bucket_name
    )
    error_message = "The longest supported project name must produce valid, distinct S3 bucket names."
  }
}

run "avoid_reserved_s3_prefixes" {
  command = plan
  variables {
    project_name = "amzn-s3-demo-project"
    environment  = "dev"
  }
  plan_options {
    target = [module.storage]
  }
  assert {
    condition = (
      startswith(output.log_s3_bucket_name, "kit-") &&
      startswith(output.output_s3_bucket_name, "kit-") &&
      length(output.log_s3_bucket_name) <= 63 &&
      length(output.output_s3_bucket_name) <= 63
    )
    error_message = "Project names must not produce bucket names with a reserved S3 prefix."
  }
}

run "kms_context_matches_storage_names" {
  command = plan
  module {
    source = "./modules/kms"
  }
  variables {
    account_id                = "123456789012"
    aws_region                = "us-east-1"
    environment               = "staging"
    name_prefix               = "abcdefghijklmnopqrstuvwxyzabcdef-staging"
    project_name              = "abcdefghijklmnopqrstuvwxyzabcdef"
    terraform_admin_role_name = ""
    tags                      = {}
  }
  assert {
    condition = toset(flatten([
      for statement in data.aws_iam_policy_document.kms_key_policy.statement : [
        for condition in statement.condition : condition.values
        if condition.variable == "kms:EncryptionContext:aws:s3:arn"
      ]
      ])) == toset([
      "arn:aws:s3:::${run.support_the_longest_project_in_staging.log_s3_bucket_name}",
      "arn:aws:s3:::${run.support_the_longest_project_in_staging.log_s3_bucket_name}/*",
      "arn:aws:s3:::${run.support_the_longest_project_in_staging.output_s3_bucket_name}",
      "arn:aws:s3:::${run.support_the_longest_project_in_staging.output_s3_bucket_name}/*",
    ])
    error_message = "KMS encryption contexts must use the actual storage bucket names."
  }
}

run "reject_unsupported_retention" {
  command = plan
  variables {
    environment_config = {
      for environment in ["dev", "staging", "prod"] : environment => {
        lambda_memory_size         = 1024
        lambda_timeout             = 120
        log_retention_days         = 2
        api_throttling_burst_limit = 25
        api_throttling_rate_limit  = 50
        cors_allowed_origins       = ["https://app.example.com"]
      }
    }
  }
  plan_options {
    target = [module.lambda]
  }
  expect_failures = [var.environment_config]
}
