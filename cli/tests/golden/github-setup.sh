#!/usr/bin/env bash
set -euo pipefail

# CLI-owned generated file. Do not edit directly.
# Update .devsecops-pipeline.toml and rerun `devsecops render`.
# See docs/generated-artifacts.md for ownership rules.
# Review placeholder values before running.

gh variable set PROJECT_NAME --body 'golden-pipeline'
gh variable set LAMBDA_IMAGE_URI --body '123456789012.dkr.ecr.eu-central-1.amazonaws.com/golden-pipeline:sha-abc123'
gh variable set API_AUTHORIZATION_TYPE --body 'AWS_IAM'
gh variable set ENABLE_SNYK_SCAN --body 'true'
gh variable set ENABLE_HTTP_VALIDATION --body 'true'
gh variable set ENABLE_DAST --body 'true'
gh variable set PROD_APPROVAL_ENVIRONMENT --body 'prod'
gh variable set PIPELINE_CONFIG_JSON --body '{"api_authorization_type":"AWS_IAM","aws_region":"eu-central-1","backend":{"bucket":"golden-pipeline-tfstate","key":"golden-pipeline/terraform.tfstate","lock_table":"golden-pipeline-locks","region":"eu-central-1","workspace_key_prefix":"envs"},"enable_dast":true,"enable_http_validation":true,"enable_snyk_scan":true,"environments":{"dev":{"api_throttling_burst_limit":25,"api_throttling_rate_limit":50,"cors_allowed_origins":["https://dev.example.com"],"lambda_memory_size":1024,"lambda_timeout":120,"log_retention_days":30},"prod":{"api_throttling_burst_limit":50,"api_throttling_rate_limit":100,"cors_allowed_origins":["https://app.example.com"],"lambda_memory_size":2048,"lambda_timeout":300,"log_retention_days":365},"staging":{"api_throttling_burst_limit":50,"api_throttling_rate_limit":100,"cors_allowed_origins":["https://staging.example.com"],"lambda_memory_size":1536,"lambda_timeout":180,"log_retention_days":90}},"lambda_image_uri":"123456789012.dkr.ecr.eu-central-1.amazonaws.com/golden-pipeline:sha-abc123","project_name":"golden-pipeline","schema_version":1,"terraform_admin_role_name":"golden-terraform-admin","use_prod_approval_environment":true,"use_separate_aws_plan_role":true}'

gh secret set AWS_REGION --body 'eu-central-1'
gh secret set AWS_ROLE_TO_ASSUME_ARN --body "<deploy-role-arn>"
gh secret set AWS_PLAN_ROLE_TO_ASSUME_ARN --body "<plan-role-arn>"
gh secret set SNYK_TOKEN --body "<snyk-token>"
