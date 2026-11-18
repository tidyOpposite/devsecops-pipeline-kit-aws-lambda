terraform {
  backend "s3" {
    bucket               = "replace-with-your-terraform-state-bucket"
    key                  = "serverless-lambda/terraform.tfstate"
    region               = "us-east-1"
    encrypt              = true
    dynamodb_table       = "devsecops-pipeline-terraform-locks"
    workspace_key_prefix = "environments"
  }
}
