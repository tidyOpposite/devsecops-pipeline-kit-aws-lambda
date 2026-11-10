terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.expected_account_id == "" ? null : [var.expected_account_id]
}
