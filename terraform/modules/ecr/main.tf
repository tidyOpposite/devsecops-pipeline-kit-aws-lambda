resource "aws_ecr_repository" "lambda_repo" {
  force_delete         = false
  name                 = "${var.name_prefix}-lambda-repo"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = var.tags
}
