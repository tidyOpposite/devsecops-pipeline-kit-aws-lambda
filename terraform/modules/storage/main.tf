module "bucket_names" {
  source = "../bucket-names"

  account_id  = var.account_id
  name_prefix = var.name_prefix
}

locals {
  log_bucket_name    = module.bucket_names.names["access-logs"]
  output_bucket_name = module.bucket_names.names["workload-data"]
}

resource "aws_s3_bucket" "log_bucket" {
  force_destroy = false
  #checkov:skip=CKV_AWS_144:Cross-region replication is an operator DR choice outside the default single-region kit.
  #checkov:skip=CKV2_AWS_62:Access logging and lifecycle are enabled; event notifications are workload-specific.
  #checkov:skip=CKV_AWS_145:S3 server access logging destination buckets must use SSE-S3 instead of default SSE-KMS for reliable log delivery.
  bucket = local.log_bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "log_bucket_versioning" {
  bucket = aws_s3_bucket.log_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "log_bucket_lifecycle" {
  bucket = aws_s3_bucket.log_bucket.id

  rule {
    id     = "expire-old-access-logs"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    expiration {
      days = 365
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "log_bucket_sse" {
  bucket = aws_s3_bucket.log_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "log_bucket_pab" {
  bucket                  = aws_s3_bucket.log_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "s3_log_bucket_policy_doc" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.log_bucket.arn,
      "${aws_s3_bucket.log_bucket.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "AllowLogDelivery"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.log_bucket.arn}/*"]

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.output_bucket.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_s3_bucket_policy" "s3_log_bucket_policy" {
  bucket = aws_s3_bucket.log_bucket.id
  policy = data.aws_iam_policy_document.s3_log_bucket_policy_doc.json
}

resource "aws_s3_bucket" "output_bucket" {
  force_destroy = false
  #checkov:skip=CKV_AWS_144:Cross-region replication is an operator DR choice outside the default single-region kit.
  #checkov:skip=CKV2_AWS_62:Event notifications are application-specific and not required for the generic workload output bucket.
  bucket = local.output_bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "output_bucket_versioning" {
  bucket = aws_s3_bucket.output_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "output_bucket_lifecycle" {
  bucket = aws_s3_bucket.output_bucket.id

  rule {
    id     = "expire-old-workload-data-versions"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "output_bucket_sse" {
  bucket = aws_s3_bucket.output_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "output_bucket_pab" {
  bucket                  = aws_s3_bucket.output_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "output_bucket_policy_doc" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.output_bucket.arn,
      "${aws_s3_bucket.output_bucket.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "output_bucket_policy" {
  bucket = aws_s3_bucket.output_bucket.id
  policy = data.aws_iam_policy_document.output_bucket_policy_doc.json
}

resource "aws_s3_bucket_logging" "output_bucket_logging" {
  bucket        = aws_s3_bucket.output_bucket.id
  target_bucket = aws_s3_bucket.log_bucket.id
  target_prefix = "log/output-bucket/"
}
