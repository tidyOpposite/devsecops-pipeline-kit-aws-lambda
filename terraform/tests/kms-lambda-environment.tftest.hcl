mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

run "lab_operator_can_configure_encrypted_lambda_environment" {
  command = plan
  module {
    source = "./modules/kms"
  }
  variables {
    account_id                = "123456789012"
    aws_region                = "eu-north-1"
    environment               = "dev"
    name_prefix               = "example-dev"
    project_name              = "example"
    terraform_admin_role_name = ""
    tags                      = {}
  }
  assert {
    condition = anytrue([
      for statement in data.aws_iam_policy_document.kms_key_policy.statement :
      statement.sid == "AllowLambdaConfigurationUsage" &&
      toset(statement.actions) == toset(["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]) &&
      alltrue([for principal in statement.principals : principal.type == "AWS" && toset(principal.identifiers) == toset(["arn:aws:iam::123456789012:root"])]) &&
      length(statement.principals) == 1 &&
      toset(statement.resources) == toset(["*"]) &&
      anytrue([for condition in statement.condition : condition.test == "StringEquals" && condition.variable == "kms:ViaService" && toset(condition.values) == toset(["lambda.eu-north-1.amazonaws.com"])])
    ])
    error_message = "The lab operator needs Encrypt/Decrypt/GenerateDataKey on this key through regional Lambda; key administration alone cannot create a function."
  }
}

run "deployment_role_uses_only_regional_lambda_crypto_permission" {
  command = plan
  module {
    source = "./modules/kms"
  }
  variables {
    account_id                = "123456789012"
    aws_region                = "us-east-1"
    environment               = "prod"
    name_prefix               = "example-prod"
    project_name              = "example"
    terraform_admin_role_name = "terraform-deployer"
    tags                      = {}
  }
  assert {
    condition = anytrue([
      for statement in data.aws_iam_policy_document.kms_key_policy.statement :
      statement.sid == "AllowLambdaConfigurationUsage" &&
      toset(statement.actions) == toset(["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]) &&
      alltrue([for principal in statement.principals : principal.type == "AWS" && toset(principal.identifiers) == toset(["arn:aws:iam::123456789012:root", "arn:aws:iam::123456789012:role/terraform-deployer"])]) &&
      length(statement.principals) == 1 &&
      toset(statement.resources) == toset(["*"]) &&
      anytrue([for condition in statement.condition : condition.test == "StringEquals" && condition.variable == "kms:ViaService" && toset(condition.values) == toset(["lambda.us-east-1.amazonaws.com"])])
    ])
    error_message = "The deployment role must receive the same Lambda-only permission in its configured account/region, without a wildcard principal or extra crypto actions."
  }
}
