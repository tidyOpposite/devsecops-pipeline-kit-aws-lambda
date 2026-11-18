locals {
  function_name = "${var.name_prefix}-lambda"
  image_uri     = var.lambda_image_uri
}

resource "aws_sqs_queue" "lambda_dlq" {
  name                              = "${var.name_prefix}-lambda-dlq"
  kms_master_key_id                 = var.kms_key_arn
  kms_data_key_reuse_period_seconds = 300
  tags                              = var.tags
}

data "aws_iam_policy_document" "lambda_assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda_execution_policy" {
  statement {
    sid    = "AllowCloudWatchLogWrites"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda_log_group.arn}:*"]
  }

  statement {
    sid       = "AllowS3OutputAccess"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${var.output_bucket_arn}/*"]
  }

  statement {
    sid       = "AllowDLQPublish"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.lambda_dlq.arn]
  }

  statement {
    sid    = "AllowXRay"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AllowKMSUsageForLambda"
    effect = "Allow"
    actions = [
      "kms:GenerateDataKey",
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:ReEncrypt*",
      "kms:DescribeKey",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role" "lambda_exec_role" {
  name               = "${var.name_prefix}-lambda-exec-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role_policy.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "lambda_execution_policy" {
  name   = "${var.name_prefix}-lambda-execution-policy"
  role   = aws_iam_role.lambda_exec_role.id
  policy = data.aws_iam_policy_document.lambda_execution_policy.json
}

resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

resource "aws_lambda_function" "workload" {
  #checkov:skip=CKV_AWS_117:The generic Lambda image is not placed in a VPC by default; workloads add VPC config when private network access is required.
  #checkov:skip=CKV_AWS_272:Lambda code signing does not apply to container image package type; image immutability and scanner gates are enforced instead.
  function_name                  = local.function_name
  role                           = aws_iam_role.lambda_exec_role.arn
  package_type                   = "Image"
  image_uri                      = local.image_uri
  architectures                  = ["x86_64"]
  kms_key_arn                    = var.kms_key_arn
  memory_size                    = var.lambda_memory_size
  reserved_concurrent_executions = var.reserved_concurrent_executions
  timeout                        = var.lambda_timeout

  dead_letter_config {
    target_arn = aws_sqs_queue.lambda_dlq.arn
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      ENVIRONMENT        = var.environment
      OUTPUT_BUCKET_NAME = var.output_bucket_name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_log_group,
    aws_iam_role_policy.lambda_execution_policy,
  ]

  lifecycle {
    precondition {
      condition     = var.lambda_image_uri != "" && !can(regex(":(latest|bootstrap)$", lower(var.lambda_image_uri)))
      error_message = "lambda_image_uri must be set to an immutable image URI before planning or applying the Lambda workload."
    }
  }

  tags = var.tags
}
