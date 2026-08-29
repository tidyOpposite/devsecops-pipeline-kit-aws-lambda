# Command Inventory

This document records the current `devsecops` command surface and the product
status of each command. It is a product contract: users should know which
commands are the preferred workflow, which commands are compatibility aliases,
and which commands may still change.

For the normative stability, deprecation, migration, JSON, and generated
artifact contract, see [Stability contract](stability-contract.md). The same
contract is available as machine-readable JSON:

```bash
devsecops inventory --format json
```

## Status Legend

| Status | Meaning |
| --- | --- |
| Stable | Preferred command for the supported CLI workflow. Flags and behavior should remain compatible within normal semver expectations. |
| Experimental | Useful command, but command shape, output, or grouping may change before `v1.0`. |
| Alias | Compatibility or shorthand command. Prefer the target command for new scripts and docs. |
| Support | User-facing inspection or explanation command. It is safe to use, but output formatting may change as the CLI improves. |

## Recommended First Run

The README quick start and `devsecops --help` use the same first-run path:

```bash
devsecops
devsecops setup --preset balanced --yes
devsecops status
devsecops dry-run --image-uri <immutable-ecr-image-uri>
```

`devsecops` without arguments and `devsecops status` use the same status and
next-action algorithm as the interactive menu. Human-readable commands repeat
that recommendation after their primary output; machine-readable output
remains clean. Use
`devsecops menu` when you prefer the interactive path.

For the full resumable wizard, use `devsecops setup` interactively. Demo mode
(`--mode demo`) completes the local no-credentials path in one command;
`--mode standard` and `--mode production` keep cloud connection stages in
scope.

## Preferred Terminology

| Preferred product term | Compatibility names | Use it for |
| --- | --- | --- |
| `setup` | `start`, `config new`; `compose` remains an Advanced editor | Starting or resuming initial project setup. |
| `status` | `dashboard`, `readiness`, `next` | One score, status areas, blockers, and the next action. |
| `image validate` | `preflight` | Validating the Lambda image before deployment. |
| `generate` / “Generate deployment files” | `render`, `--render` | Creating CLI-owned Terraform and GitHub helper files. |
| `doctor` / “Diagnose problems” | — | Technical troubleshooting after status identifies a problem. |
| `Advanced` / release maintenance | `criteria`, `evidence`, `inventory` | Maintainer evidence and contract work, not the first-run path. |

Compatibility names remain callable through the documented deprecation window,
but they are hidden from primary help and shell completion.

## Commands

| Command | Status | Scope | Notes |
| --- | --- | --- | --- |
| `devsecops` | Stable | First success | Prints compact project status and the shared next action without prompting. |
| `devsecops menu` | Stable | Interactive CLI | Opens six product sections: Continue setup, Status, Deploy, Diagnose problems, Configuration, and Advanced. Technical tools remain nested under their relevant section. |
| `devsecops setup` | Stable | First success | Resumable nine-stage onboarding for mode, dependencies, config, image, backend, AWS identity, GitHub/OIDC, dry-run, and summary. AWS checks are read-only. GitHub changes require confirmation or explicit `--apply-github`; `--yes` alone never authorizes them. |
| `devsecops status` | Stable | First success | Shows one overall score, status by area, blockers, and one next action. Supports `--deep`, `--strict`, `--watch`, and `--format human\|compact\|json`. |
| `devsecops dry-run` | Stable | First success | Previews the first-success path without writing files or requiring AWS credentials. |
| `devsecops image validate` | Stable | First success | Checks Lambda image URI shape, immutability, and region before production deploy. |
| `devsecops health` | Stable | Operations | Validates the deployed `/health` endpoint outside GitHub Actions. Uses Terraform output unless `--url` is provided; use `--aws-sigv4` for IAM-protected API Gateway routes. |
| `devsecops generate` | Stable | Generation | Writes CLI-owned Terraform and GitHub helper artifacts. Use `--dry-run` to preview file changes. |
| `devsecops report` | Stable | Reporting | Writes a CLI-owned Markdown readiness report or JSON audit evidence with `--format json`. |
| `devsecops evidence collect` | Stable | Advanced / release | Collects local release-candidate evidence artifacts with `--rc`. |
| `devsecops criteria` | Stable | Advanced / release | Checks every Version 1.0 criterion and the external evidence gates that still block a stable tag. |
| `devsecops inventory` | Stable | Advanced / maintenance | Prints the command, JSON, generated artifact, deprecation, and migration contracts. |
| `devsecops completion <shell>` | Stable | Distribution | Prints dependency-free shell completion for `bash`, `zsh`, or `fish`. |
| `devsecops doctor` | Stable | Diagnostics | Primary diagnostics group for local, GitHub, AWS, branch, Actions, and all-in-one checks. |
| `devsecops doctor local` | Stable | Diagnostics | Checks local readiness. `--deep` adds external Terraform/AWS checks and may vary by installed tools. |
| `devsecops doctor github` | Stable | GitHub | Checks GitHub CLI, repository variables, and repository secrets. |
| `devsecops doctor aws` | Stable | AWS | Checks AWS identity, backend, and deployed resources. |
| `devsecops doctor branch` | Stable | GitHub | Checks branch protection and required checks. |
| `devsecops doctor actions` | Stable | GitHub | Shows recent GitHub Actions runs, failed jobs, failed steps, next actions, and runbook links. |
| `devsecops doctor all` | Stable | Diagnostics | Runs local, GitHub, branch, and AWS checks together. |
| `devsecops aws` | Stable | AWS | Primary AWS group for deployed output inspection and AWS doctor workflows. |
| `devsecops aws outputs` | Stable | AWS | Read-only inspection of deployed Lambda, API Gateway, and CloudWatch outputs. |
| `devsecops aws doctor` | Stable | AWS | Grouped alias for `devsecops doctor aws`. |
| `devsecops validate-config` | Alias | Configuration | Compatibility command for `devsecops config validate`. |
| `devsecops set` | Alias | Configuration | Compatibility alias for `devsecops config set`. |
| `devsecops config` | Alias | Configuration | Compatibility shorthand for `devsecops config show`. |
| `devsecops config show` | Stable | Configuration | Prints the current local source config as TOML or normalized JSON. |
| `devsecops config new` | Alias | Configuration | Lower-level compatibility entry point for clean config creation. Prefer `devsecops setup`. |
| `devsecops config validate` | Stable | Configuration | Validates the local source config before Terraform or GitHub commands run. Use `--strict` to fail on production-risk warnings. |
| `devsecops config diff` | Stable | Configuration | Shows canonical TOML drift or compares the current config against a preset. |
| `devsecops config reset` | Stable | Configuration | Resets local source config to a clean preset after taking a snapshot. |
| `devsecops config set` | Stable | Configuration | Sets one local config key. Prefer this over the legacy top-level `set` alias. |
| `devsecops config schema` | Stable | Configuration | Prints the config schema contract as JSON or Markdown. |
| `devsecops preset list` | Stable | Configuration | Lists policy presets. |
| `devsecops preset show <name>` | Stable | Configuration | Prints a preset summary. |
| `devsecops preset apply <name>` | Stable | Configuration | Applies a preset while preserving user-specific identity values. |
| `devsecops preset <name>` | Alias | Configuration | Backward-compatible shorthand for `devsecops preset apply <name>`. |
| `devsecops compose` | Experimental | Advanced configuration | Interactive control picker. Prefer `devsecops setup` for onboarding. |
| `devsecops snapshot` | Stable | Recovery | Primary snapshot group for list, show, and restore workflows. |
| `devsecops snapshot list` | Stable | Recovery | Lists local snapshots of CLI-owned files. |
| `devsecops snapshot show` | Stable | Recovery | Shows snapshot details and changes since the snapshot. |
| `devsecops snapshot restore` | Stable | Recovery | Restores local CLI-owned files from a snapshot. This is not the cloud Lambda deployment rollback. |
| `devsecops snapshots` | Alias | Recovery | Compatibility alias for snapshot listing and inspection. |
| `devsecops rollback` | Alias | Recovery | Compatibility alias for `devsecops snapshot restore`. |
| `devsecops github` | Stable | GitHub | Primary GitHub group for setup, status, branch, and GitHub doctor workflows. |
| `devsecops github setup` | Stable | GitHub | Prints, writes, or applies GitHub variable/secret setup commands through `gh`. |
| `devsecops github status` | Stable | GitHub | Shows recent GitHub Actions runs, failed jobs, failed steps, next actions, and runbook links. |
| `devsecops github branch` | Stable | GitHub | Checks branch protection and required checks. |
| `devsecops github doctor` | Stable | GitHub | Checks GitHub CLI, variables, and secrets. |
| `devsecops github-setup` | Alias | GitHub | Compatibility alias for `devsecops github setup`. |
| `devsecops gh-setup` | Alias | GitHub | Alias for `devsecops github-setup`. |
| `devsecops gh-doctor` | Alias | GitHub | Compatibility alias for `devsecops doctor github`. |
| `devsecops actions-status` | Alias | GitHub | Compatibility alias for `devsecops doctor actions`. |
| `devsecops gh-status` | Alias | GitHub | Compatibility name for `devsecops actions-status`. |
| `devsecops branch-doctor` | Alias | GitHub | Compatibility alias for `devsecops doctor branch`. |
| `devsecops aws-doctor` | Alias | AWS | Compatibility alias for `devsecops doctor aws`. |
| `devsecops terraform` | Stable | Terraform | Primary Terraform group for plan and backend bootstrap helpers. |
| `devsecops terraform plan <env>` | Stable | Terraform | Convenience wrapper for Terraform plan against an environment workspace. Delegates to Terraform without hiding Terraform output. |
| `devsecops terraform bootstrap` | Stable | Terraform | Plans or applies the Terraform backend bootstrap stack. Mutates AWS only with `--apply`. |
| `devsecops plan <env>` | Alias | Terraform | Compatibility alias for `devsecops terraform plan <env>`. |
| `devsecops bootstrap` | Alias | Terraform | Compatibility alias for `devsecops terraform bootstrap`. |
| `devsecops envs` | Support | Inspection | Prints environment settings. |
| `devsecops controls` | Support | Inspection | Prints the security controls catalog. Supports `--format json`. |
| `devsecops architecture` | Support | Inspection | Prints the architecture tree. |
| `devsecops explain [topic]` | Support | Inspection | Explains a pipeline security control. |
| `devsecops tui` | Experimental | UI | Optional Rich/Textual UI bridge. Requires installing optional dependencies. |
| `devsecops start` | Alias | Compatibility | Previous name for `devsecops setup`. |
| `devsecops next` | Alias | Compatibility | Previous next-action-only view. Prefer `devsecops status`. |
| `devsecops readiness` | Alias | Compatibility | Previous readiness-only view. Prefer `devsecops status`; legacy JSON stays stable. |
| `devsecops dashboard` | Alias | Compatibility | Previous dashboard view. Prefer `devsecops status`. |
| `devsecops preflight` | Alias | Compatibility | Previous name for `devsecops image validate`; legacy JSON stays stable. |
| `devsecops render` | Alias | Compatibility | Previous name for `devsecops generate`. |

## Examples

| Workflow | Example |
| --- | --- |
| Interactive menu | `devsecops menu` |
| Local guided demo | `devsecops setup --mode demo --yes --strict` |
| Project setup or resume | `devsecops setup --mode standard` |
| Non-interactive local inputs | `devsecops setup --mode standard --yes --image-uri <uri> --backend-bucket <bucket>` |
| Explicit GitHub/OIDC setup | `devsecops setup --apply-github --deploy-role-arn <arn> --plan-role-arn <arn>` |
| Project status and next action | `devsecops status` |
| Deep project status | `devsecops status --deep` |
| Shell completion | `devsecops completion bash` |
| Legacy clean-config entry point | `devsecops config new --preset balanced` |
| Show config | `devsecops config show --format json` |
| Validate config | `devsecops config validate` |
| Strict config validation | `devsecops config validate --strict` |
| Diff config | `devsecops config diff --preset strict` |
| Set config | `devsecops config set backend.bucket my-state-bucket --generate` |
| Reset config | `devsecops config reset --preset minimal` |
| Config schema | `devsecops config schema --format markdown` |
| Generate deployment files | `devsecops generate` |
| Preview deployment files | `devsecops generate --dry-run` |
| Audit evidence | `devsecops report --format json` |
| RC evidence collection | `devsecops evidence collect --rc` |
| Version 1.0 criteria check | `devsecops criteria --strict` |
| Production evidence guide | `docs/production-deployment-evidence.md` |
| Release candidate checklist | `docs/v1.0.0-release-candidate-checklist.md` |
| Stability contract JSON | `devsecops inventory --format json` |
| First-success dry run | `devsecops dry-run --image-uri <immutable-ecr-image-uri>` |
| Validate image | `devsecops image validate --image-uri <immutable-ecr-image-uri>` |
| Status JSON | `devsecops status --format json` |
| Strict status | `devsecops status --strict --format compact` |
| Local doctor | `devsecops doctor local --deep --format compact` |
| GitHub doctor | `devsecops doctor github --format json` |
| AWS doctor | `devsecops doctor aws --environment prod --strict` |
| AWS outputs | `devsecops aws outputs --environment prod --format json` |
| Branch doctor | `devsecops doctor branch --branch main` |
| Actions status | `devsecops doctor actions --format compact` |
| Health validation | `devsecops health --url <health-url> --aws-sigv4` |
| All diagnostics | `devsecops doctor all --format json` |
| GitHub setup | `devsecops github setup --write` |
| GitHub status | `devsecops github status --format json` |
| GitHub branch | `devsecops github branch --branch main` |
| Terraform plan | `devsecops terraform plan dev --create-workspace` |
| Terraform bootstrap | `devsecops terraform bootstrap --apply` |
| Snapshot list | `devsecops snapshot list --format json` |
| Snapshot show | `devsecops snapshot show 1` |
| Snapshot restore | `devsecops snapshot restore --last --dry-run` |
| Preset list | `devsecops preset list` |
| Preset show | `devsecops preset show strict` |
| Preset apply | `devsecops preset apply strict --generate` |
| Advanced control editor | `devsecops compose` |
| Environment table | `devsecops envs` |
| Controls matrix | `devsecops controls` |
| Controls JSON | `devsecops controls --format json` |
| Architecture tree | `devsecops architecture` |
| Explain control | `devsecops explain oidc` |
| Optional TUI | `devsecops tui` |
| Legacy init alias | `devsecops init --defaults` |
| Legacy set alias | `devsecops set backend.bucket my-state-bucket --render` |
| Legacy validate alias | `devsecops validate-config` |
| Legacy GitHub setup alias | `devsecops github-setup --write` |
| Legacy GitHub doctor alias | `devsecops gh-doctor` |
| Legacy AWS doctor alias | `devsecops aws-doctor --environment prod` |
| Legacy Actions alias | `devsecops actions-status` |
| Legacy branch alias | `devsecops branch-doctor --branch main` |
| Legacy Terraform plan alias | `devsecops plan dev --create-workspace` |
| Legacy Terraform bootstrap alias | `devsecops bootstrap --apply` |
| Legacy snapshot alias | `devsecops snapshots --show 1` |
| Legacy rollback alias | `devsecops rollback --last --dry-run` |

## Product Boundary

The CLI owns local configuration and generated helper artifacts. Terraform,
GitHub Actions, AWS resources, and scanner tools are still transparent
execution layers that operators can inspect directly.

Commands that mutate local files create snapshots where appropriate. Commands
that mutate GitHub or AWS require explicit flags such as `--apply` and should
be reviewed before use in production.

## Stable Script Contract

Stable commands, documented flags, exit codes, generated file paths, and JSON
`kind` values are safe to script against within normal semver expectations.
Human table layout can still be improved. Prefer JSON output for automation:

```bash
devsecops config validate --format json
devsecops status --format json
devsecops doctor github --format json
devsecops aws outputs --format json
devsecops inventory --format json
```

Aliases remain callable through at least `v1.0.0`, but new scripts should use
the grouped stable command. Experimental commands are not part of the
first-success workflow and can change in a `0.x` minor release.

## Production Evidence Workflow

Milestone 8 production proof uses existing stable commands instead of a new
command surface:

```bash
devsecops config validate --strict --format json
devsecops status --strict --format json
devsecops report --format json
devsecops doctor github --format json
devsecops doctor branch --branch main --format json
devsecops github status --format json
devsecops aws outputs --environment prod --format json
devsecops doctor aws --environment prod --strict --format json
devsecops health --url <health-url> --aws-sigv4 --format json
```

Use [Production deployment evidence](production-deployment-evidence.md) for the
full evidence bundle layout, production dispatch commands, post-deploy
checklist, and runbook update gate.

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Command completed successfully. |
| `1` | Validation failed or the requested local selection was invalid. |
| `2` | Required external tool is missing. |
| `3` | External authentication is missing or invalid. |
| `70` | Unexpected runtime error. |
| `130` | Command was interrupted. |
