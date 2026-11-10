# This fixture is used only by explicit sandbox acceptance. It has no remote
# backend and never imports deployment state or existing workload resources.
terraform {
  required_version = ">= 1.10.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
}

variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id)) && var.expected_account_id != var.production_account_id
    error_message = "Acceptance requires a dedicated sandbox account distinct from production."
  }
}

variable "production_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.production_account_id))
    error_message = "Independently confirm the production account ID."
  }
}

variable "project_name" {
  type = string
  validation {
    condition     = can(regex("^acceptance-[a-f0-9]{21}$", var.project_name))
    error_message = "Use the unique 32-character acceptance prefix generated for this run."
  }
}

variable "aws_region" {
  type = string
}

variable "lambda_image_uri" {
  type = string
}

locals {
  name_prefix = "${var.project_name}-staging"
  tags        = { Project = var.project_name, Purpose = "IsolatedRuntimeAcceptance", ManagedBy = "TerraformTest" }
}

module "bucket_names" {
  source      = "../modules/bucket-names"
  account_id  = var.expected_account_id
  name_prefix = local.name_prefix
}

module "kms" {
  source                    = "../modules/kms"
  account_id                = var.expected_account_id
  aws_region                = var.aws_region
  environment               = "staging"
  name_prefix               = local.name_prefix
  project_name              = var.project_name
  terraform_admin_role_name = ""
  tags                      = local.tags
}

# Acceptance buckets contain only fixture data, never deployment state or user
# data. force_destroy allows Terraform test to clean this unique fixture fully.
resource "aws_s3_bucket" "fixture" {
  for_each      = module.bucket_names.names
  bucket        = each.value
  force_destroy = true
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "fixture" {
  for_each                = aws_s3_bucket.fixture
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "fixture" {
  for_each = aws_s3_bucket.fixture
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = module.kms.key_arn
    }
  }
}

resource "aws_s3_bucket_versioning" "fixture" {
  for_each = aws_s3_bucket.fixture
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "fixture" {
  for_each = aws_s3_bucket.fixture
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Deny", Principal = "*", Action = "s3:*",
      Resource  = [each.value.arn, "${each.value.arn}/*"],
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

module "lambda" {
  source                         = "../modules/lambda"
  environment                    = "staging"
  kms_key_arn                    = module.kms.key_arn
  lambda_image_uri               = var.lambda_image_uri
  lambda_memory_size             = 128
  lambda_timeout                 = 30
  log_retention_days             = 1096
  name_prefix                    = local.name_prefix
  output_bucket_arn              = aws_s3_bucket.fixture["workload-data"].arn
  output_bucket_name             = aws_s3_bucket.fixture["workload-data"].id
  reserved_concurrent_executions = 1
  tags                           = local.tags
}

data "aws_cloudwatch_log_group" "live" {
  name       = "/aws/lambda/${module.lambda.function_name}"
  depends_on = [module.lambda]
}

data "aws_lambda_function" "live" {
  function_name = module.lambda.function_name
  depends_on    = [module.lambda]
}

output "bucket_names" {
  value = [for bucket in aws_s3_bucket.fixture : bucket.bucket]
}

output "retention_days" {
  value = data.aws_cloudwatch_log_group.live.retention_in_days
}

output "lambda_environment" {
  value = data.aws_lambda_function.live.environment[0].variables
}
