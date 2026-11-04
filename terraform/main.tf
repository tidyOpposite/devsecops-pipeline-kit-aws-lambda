data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

module "kms" {
  source = "./modules/kms"

  account_id                = data.aws_caller_identity.current.account_id
  aws_region                = data.aws_region.current.name
  environment               = local.environment
  name_prefix               = local.name_prefix
  project_name              = var.project_name
  terraform_admin_role_name = var.terraform_admin_role_name
  tags                      = local.common_tags
}

module "storage" {
  source = "./modules/storage"

  account_id  = data.aws_caller_identity.current.account_id
  kms_key_arn = module.kms.key_arn
  name_prefix = local.name_prefix
  tags        = local.common_tags
}

module "ecr" {
  source = "./modules/ecr"

  kms_key_arn = module.kms.key_arn
  name_prefix = local.name_prefix
  tags        = local.common_tags
}

module "lambda" {
  source = "./modules/lambda"

  environment                    = local.environment
  kms_key_arn                    = module.kms.key_arn
  lambda_image_uri               = var.lambda_image_uri
  lambda_memory_size             = try(local.environment_settings.lambda_memory_size, var.lambda_memory_size)
  lambda_timeout                 = try(local.environment_settings.lambda_timeout, var.lambda_timeout)
  log_retention_days             = local.environment_settings.log_retention_days
  name_prefix                    = local.name_prefix
  output_bucket_arn              = module.storage.output_bucket_arn
  output_bucket_name             = module.storage.output_bucket_name
  reserved_concurrent_executions = var.lambda_reserved_concurrent_executions
  tags                           = local.common_tags
}

module "api_gateway" {
  source = "./modules/api-gateway"

  authorization_type         = var.api_authorization_type
  api_throttling_burst_limit = local.environment_settings.api_throttling_burst_limit
  api_throttling_rate_limit  = local.environment_settings.api_throttling_rate_limit
  cors_allowed_origins       = local.environment_settings.cors_allowed_origins
  kms_key_arn                = module.kms.key_arn
  lambda_invoke_arn          = module.lambda.invoke_arn
  log_retention_days         = local.environment_settings.log_retention_days
  name_prefix                = local.name_prefix
  tags                       = local.common_tags
}

resource "aws_lambda_permission" "api_gw_permission" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}
