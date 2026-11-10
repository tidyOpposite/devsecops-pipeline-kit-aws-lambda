# These applies and Terraform test's automatic teardown use only mock AWS.
# The product keeps data deletion separate from infrastructure destruction.
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

run "workload_buckets_require_explicit_data_cleanup" {
  command = apply
  module {
    source = "./modules/storage"
  }
  variables {
    account_id  = "123456789012"
    name_prefix = "teardown-fixture-dev"
    kms_key_arn = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111"
    tags        = {}
  }
  assert {
    condition     = !aws_s3_bucket.output_bucket.force_destroy && !aws_s3_bucket.log_bucket.force_destroy
    error_message = "Product buckets must not silently purge retained data during destroy."
  }
  assert {
    condition = (
      aws_s3_bucket_versioning.output_bucket_versioning.versioning_configuration[0].status == "Enabled" &&
      aws_s3_bucket_versioning.log_bucket_versioning.versioning_configuration[0].status == "Enabled"
    )
    error_message = "Cleanup must account for versioned workload data and access logs."
  }
}

run "images_require_explicit_retention_decisions" {
  command = apply
  module {
    source = "./modules/ecr"
  }
  variables {
    name_prefix = "teardown-fixture-dev"
    kms_key_arn = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111"
    tags        = {}
  }
  assert {
    condition     = !aws_ecr_repository.lambda_repo.force_delete
    error_message = "Destroy must not silently remove images still needed for recovery or another workload."
  }
}

run "backend_teardown_is_separate_and_preserves_nonempty_buckets" {
  command = apply
  module {
    source = "./bootstrap"
  }
  variables {
    expected_account_id = "123456789012"
    aws_region          = "us-east-1"
    state_bucket_name   = "teardown-fixture-state"
    lock_table_name     = "teardown-fixture-locks"
  }
  assert {
    condition = (
      !aws_s3_bucket.terraform_state.force_destroy &&
      !aws_s3_bucket.terraform_state_logs.force_destroy &&
      aws_kms_key.terraform_state.deletion_window_in_days == 7
    )
    error_message = "Backend data must be resolved before its destroy; key removal remains scheduled."
  }
}

run "reject_invalid_manual_account_guard" {
  command = plan
  # Terraform 1.10 can prune provider-only variable validation from a targeted
  # mock plan. Exercise the full root plan, with a valid unrelated image input.
  variables {
    expected_account_id = "not-an-account"
    lambda_image_uri    = "123456789012.dkr.ecr.us-east-1.amazonaws.com/fixture@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  expect_failures = [var.expected_account_id]
}
