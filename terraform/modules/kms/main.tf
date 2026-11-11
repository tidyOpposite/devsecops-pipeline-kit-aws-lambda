module "bucket_names" {
  source = "../bucket-names"

  account_id  = var.account_id
  name_prefix = var.name_prefix
}

locals {
  terraform_admin_role_arn = var.terraform_admin_role_name == "" ? null : "arn:aws:iam::${var.account_id}:role/${var.terraform_admin_role_name}"
  key_admin_principals = compact([
    "arn:aws:iam::${var.account_id}:root",
    local.terraform_admin_role_arn,
  ])
  log_bucket_arn    = "arn:aws:s3:::${module.bucket_names.names["access-logs"]}"
  output_bucket_arn = "arn:aws:s3:::${module.bucket_names.names["workload-data"]}"
  ecr_repo_arn      = "arn:aws:ecr:${var.aws_region}:${var.account_id}:repository/${var.name_prefix}-lambda-repo"
  lambda_dlq_arn    = "arn:aws:sqs:${var.aws_region}:${var.account_id}:${var.name_prefix}-lambda-dlq"
}

#checkov:skip=CKV_AWS_109:KMS key policies must use resource "*" for the current key; principals and service conditions scope access.
#checkov:skip=CKV_AWS_111:KMS key policies must use resource "*" for the current key; write access is constrained by principal and service context.
#checkov:skip=CKV_AWS_356:KMS key policies must use resource "*" for the current key; the policy is bound to aws_kms_key.encryption_key.
data "aws_iam_policy_document" "kms_key_policy" {
  #checkov:skip=CKV_AWS_109:KMS key policies must use resource "*" for the current key; principals and service conditions scope access.
  #checkov:skip=CKV_AWS_111:KMS key policies must use resource "*" for the current key; write access is constrained by principal and service context.
  #checkov:skip=CKV_AWS_356:KMS key policies must use resource "*" for the current key; the policy is bound to aws_kms_key.encryption_key.
  statement {
    sid    = "EnableRootAndTerraformRolePermissions"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = local.key_admin_principals
    }
    actions = [
      "kms:Create*",
      "kms:Describe*",
      "kms:Enable*",
      "kms:List*",
      "kms:Put*",
      "kms:Update*",
      "kms:Revoke*",
      "kms:Disable*",
      "kms:Get*",
      "kms:Delete*",
      "kms:TagResource",
      "kms:UntagResource",
      "kms:ScheduleKeyDeletion",
      "kms:CancelKeyDeletion",
    ]
    resources = ["*"]
  }

  # Lambda encrypts environment configuration and optimized container images
  # on behalf of the deployer; key administration/CreateGrant is insufficient.
  statement {
    sid    = "AllowLambdaConfigurationUsage"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = local.key_admin_principals
    }
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["lambda.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid    = "AllowS3ServiceUsage"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        local.log_bucket_arn,
        "${local.log_bucket_arn}/*",
        local.output_bucket_arn,
        "${local.output_bucket_arn}/*",
      ]
    }
  }

  statement {
    sid    = "AllowSQSServiceUsage"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["sqs.amazonaws.com"]
    }
    actions = [
      "kms:GenerateDataKey",
      "kms:Decrypt",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["sqs.${var.aws_region}.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:sqs:arn"
      values   = [local.lambda_dlq_arn]
    }
  }

  statement {
    sid    = "AllowCloudWatchLogsServiceUsage"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt*",
      "kms:Decrypt*",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.name_prefix}-lambda",
        "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.name_prefix}-lambda:*",
        "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/apigateway/${var.name_prefix}-http-api",
        "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/apigateway/${var.name_prefix}-http-api:*",
      ]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }

  statement {
    sid    = "AllowECRServiceUsage"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ecr.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ecr.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_kms_key" "encryption_key" {
  description             = "KMS key for ${var.name_prefix}"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.kms_key_policy.json
  tags                    = var.tags
}

resource "aws_kms_alias" "encryption_key" {
  name          = "alias/${var.name_prefix}-encryption"
  target_key_id = aws_kms_key.encryption_key.key_id
}
