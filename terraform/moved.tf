moved {
  from = aws_kms_key.encryption_key
  to   = module.kms.aws_kms_key.encryption_key
}

moved {
  from = aws_s3_bucket.log_bucket
  to   = module.storage.aws_s3_bucket.log_bucket
}

moved {
  from = aws_s3_bucket_versioning.log_bucket_versioning
  to   = module.storage.aws_s3_bucket_versioning.log_bucket_versioning
}

moved {
  from = aws_s3_bucket_policy.s3_log_bucket_policy
  to   = module.storage.aws_s3_bucket_policy.s3_log_bucket_policy
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.log_bucket_sse
  to   = module.storage.aws_s3_bucket_server_side_encryption_configuration.log_bucket_sse
}

moved {
  from = aws_s3_bucket_public_access_block.log_bucket_pab
  to   = module.storage.aws_s3_bucket_public_access_block.log_bucket_pab
}

moved {
  from = aws_s3_bucket.output_bucket
  to   = module.storage.aws_s3_bucket.output_bucket
}

moved {
  from = aws_s3_bucket_versioning.output_bucket_versioning
  to   = module.storage.aws_s3_bucket_versioning.output_bucket_versioning
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.output_bucket_sse
  to   = module.storage.aws_s3_bucket_server_side_encryption_configuration.output_bucket_sse
}

moved {
  from = aws_s3_bucket_public_access_block.output_bucket_pab
  to   = module.storage.aws_s3_bucket_public_access_block.output_bucket_pab
}

moved {
  from = aws_s3_bucket_logging.output_bucket_logging
  to   = module.storage.aws_s3_bucket_logging.output_bucket_logging
}

moved {
  from = aws_ecr_repository.lambda_repo
  to   = module.ecr.aws_ecr_repository.lambda_repo
}

moved {
  from = aws_sqs_queue.lambda_dlq
  to   = module.lambda.aws_sqs_queue.lambda_dlq
}

moved {
  from = aws_iam_role.lambda_exec_role
  to   = module.lambda.aws_iam_role.lambda_exec_role
}

moved {
  from = aws_iam_role_policy.lambda_execution_policy
  to   = module.lambda.aws_iam_role_policy.lambda_execution_policy
}

moved {
  from = aws_cloudwatch_log_group.lambda_log_group
  to   = module.lambda.aws_cloudwatch_log_group.lambda_log_group
}

moved {
  from = aws_cloudwatch_log_group.api_gw_log_group
  to   = module.api_gateway.aws_cloudwatch_log_group.api_gw_log_group
}

moved {
  from = aws_apigatewayv2_api.http_api
  to   = module.api_gateway.aws_apigatewayv2_api.http_api
}

moved {
  from = aws_apigatewayv2_integration.lambda_integration
  to   = module.api_gateway.aws_apigatewayv2_integration.lambda_integration
}

moved {
  from = aws_apigatewayv2_route.default_route
  to   = module.api_gateway.aws_apigatewayv2_route.default_route
}

moved {
  from = aws_apigatewayv2_stage.default_stage
  to   = module.api_gateway.aws_apigatewayv2_stage.default_stage
}
