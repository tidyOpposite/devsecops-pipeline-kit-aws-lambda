#!/usr/bin/env bash
set -euo pipefail

# CLI-owned generated file. Do not edit directly.
# Update .devsecops-pipeline.toml and rerun `devsecops render`.
# See docs/generated-artifacts.md for ownership rules.
# Run from the project checkout with OWNER/REPO and setup options.
# Example options: --deploy-role-arn <deploy-role-arn> --plan-role-arn <plan-role-arn>
# Include --snyk-token <snyk-token> when SNYK_TOKEN is not configured.

repository="${1:?Usage: github-setup.sh OWNER/REPO [setup options]}"
shift
exec devsecops github setup --apply --repo "$repository" "$@"
