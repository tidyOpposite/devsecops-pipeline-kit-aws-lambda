# Single-operator AWS lab

`devsecops lab` demonstrates the real shared Terraform modules and an IAM
protected Lambda API with one operator in one AWS account. It is always `dev`.
Production deployment still requires its normal GitHub/OIDC/reviewer controls;
the distinct-account runtime acceptance workflow is unchanged. These production
integrations are experimental and outside stable 1.0 acceptance. The local CLI
and this single-operator lab form the stable target.

This command is in unpublished source `0.16.0b2.dev0`, after beta.1. Install the
CLI from the matching checkout in a virtual environment; beta.1 release assets
do not include it. AWS CLI v2, a signed-in named profile, Terraform >=1.10.5
and Docker for publishing the optional example are required. No permanent
access key is required; CLI login/SSO credentials are resolved in memory via
AWS CLI `export-credentials`, including for the pinned Terraform provider.
This bridge follows the [AWS login guidance](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html)
and [process credential contract](https://docs.aws.amazon.com/sdkref/latest/guide/feature-process-credentials.html).
Interpreter and checkout paths may contain spaces. Keep the installed CLI and
Terraform checkout at the same revision.
The lab executes Terraform directly; GitHub Actions and its production scanner
jobs are not part of this path. Run image/security checks separately before
using the demonstration to make any security claims.

## Scope and prerequisites

Use a commercial AWS region and explicitly confirm the 12-digit account ID.
The CLI checks STS before provider actions. Terraform additionally restricts
the allowed account. The lab gets a random project prefix and only manages
its own module addresses and ownership tags. Existing production configuration,
workspaces, backend and GitHub settings are not used.

Local state, plans and evidence live under `.devsecops/labs/<name>/`, ignored by
Git. Keep this directory private and backed up: losing local state is not a
cleanup mechanism. Avoid concurrent external Terraform changes while a plan is
under review. A local operator lock prevents simultaneous CLI operations.

**Concurrency:** the default remains a reservation of 10. Before workload
plan/apply the CLI reads the account quota, unreserved pool and this function's
existing reservation. Allocating reserved capacity must leave the AWS-required
100 units unreserved; simply changing 10 to 1 does not solve a new account quota
of 10. See [AWS reserved concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html).

For this separate dev lab, explicitly select shared-pool mode with
`lab concurrency NAME --mode unreserved`. Terraform then uses `-1`, supported
by the [pinned provider](https://github.com/hashicorp/terraform-provider-aws/blob/v5.100.0/internal/service/lambda/function.go).
This removes a function reservation: the function shares the account's finite
quota with other unreserved functions. It has no dedicated cap or capacity
guarantee. A quota of 10 still limits the account to 10 concurrent executions;
this setting does not increase that quota. Keep IAM authorization, send a few
sequential demonstration requests and avoid load testing in a shared account.

Inspect policy with `lab concurrency NAME`. Return to reservations using
`--mode reserved --reserved-executions 10` when the actual quota allows it.
Zero (disabled invocations), fractional and invalid values are rejected.
Policy changes are local, invalidate existing saved plans and require a new
review before any AWS mutation. They can also be selected in Deploy →
Single-operator AWS lab → Configure Lambda concurrency.

## Registry, then workload

Commands run from the matching checkout. Substitute your own account, region
and signed-in profile; these are identifiers, not keys:

```bash
devsecops lab init diploma --expected-account-id 123456789012 \
  --region eu-north-1 --profile diploma
# For a low-quota dev account, explicitly choose the shared account pool:
devsecops lab concurrency diploma --mode unreserved
devsecops lab status diploma
devsecops lab plan diploma --stage registry
```

`plan` reads AWS and writes local artifacts. It does not apply infrastructure.
Review the full `plan.txt` path in its output. It targets ECR/KMS only because
Lambda needs a published image before creation. Other stages use full plans.
The output includes a plan ID and the SHA-256 of `review.json`:

```bash
devsecops lab apply diploma --plan-id PLAN_ID --sha256 REVIEW_SHA256
devsecops lab apply diploma --plan-id PLAN_ID --sha256 REVIEW_SHA256 --yes
```

Without `--yes`, apply displays the review only. In the menu, choose **Deploy
and operate → Single-operator AWS lab → Review/apply a saved plan**: the full
saved plan is displayed before a confirmation that defaults to No. Registry
apply creates AWS resources and can incur costs.

Plans expire after one hour. Changed source, provider lock, settings, state,
plan bytes or live image cause rejection. An attempted plan cannot be reused;
after a failure inspect its evidence and create a new plan.

Build the three [Text Stats images](../examples/text-stats/README.md). The
registry-ready output supplies this lab's unique ECR repository URL. Authenticate
Docker without printing or recording the login token:

```bash
aws ecr get-login-password --profile diploma --region eu-north-1 |
  docker login --username AWS --password-stdin REGISTRY_HOST
docker tag devsecops-text-stats:demo-a REPOSITORY_URL:COMMIT-demo-a
docker push REPOSITORY_URL:COMMIT-demo-a
```

Repeat tagging/pushing B and the intentionally failing image with unique tags.
Record ECR digests from the actual push/readback. Use the **digest URI** for each
deployment. The CLI verifies the stored manifest, pull access and `linux/amd64`
configuration in this lab's repository.

```bash
devsecops lab plan diploma --stage workload --image-uri REPOSITORY_URL@sha256:DIGEST_A
# Read plan.txt, then apply that plan ID and review hash with --yes.
devsecops lab status diploma
devsecops lab request diploma --path /version
devsecops lab request diploma --method POST --path /analyze \
  --body '{"text":"Привіт, дипломний проєкт!"}'
devsecops lab logs diploma
```

`logs` reads all CloudWatch pages in a fixed 15-minute window and returns the
latest 50 events in chronological order. A short or empty page can still have a
continuation token; it does not mean the query is complete. Busy windows may
require several read requests. A page retrieval failure fails the command
instead of reporting incomplete output as success.

Each successful workload apply requires the actual Lambda resolved digest,
Terraform state image and signed `/health` HTTP 2xx to agree. Configured,
state and live concurrency policy must also match. Capacity is checked again
at apply because other functions can consume it after plan review. A preflight
pass does not lock the shared pool or prevent later throttling. Requests are
limited to this lab's verified regional API and supported example routes;
redirects are not followed. No signing credentials or authorization headers
are saved in evidence. Response bodies and application logs are private and
may contain application data.

## Update, failure and recovery

1. Apply healthy A; record `/version`, `/analyze`, health and logs.
2. Plan/apply healthy B; record the new digest, state and version response.
3. Plan/apply the failing image C. **Expected exit code: 1.** Failed health
   must trigger code restoration to the prior verified healthy B, wait for the
   update, refresh Terraform state and require healthy readback. Evidence must
   say `status=failed` and `recovery.status=recovered`, with B active.
4. For manual rollback, use `lab plan diploma --stage rollback --image-uri
   REPOSITORY_URL@sha256:DIGEST_A`, review/apply it and verify A again.

The previous image is pull-verified and health-checked before an update plan.
Recovery never deletes resources, and it only targets the same recorded Lambda
ARN and retained digest. If the first deployment fails, there is no known good
version to restore: keep state and inspect the partial apply. If restoration
or refresh fails, evidence reports `recovery-failed`; it cannot report a healthy
deployment. Interruptions during apply are recorded and recovery is attempted
when a previous function exists. A kill/power loss cannot guarantee recovery;
inspect state/live resources and replan rather than replaying the old plan.

## Evidence and screenshots

Every operation writes private `evidence/<timestamp-id>/` with scope/source
fingerprint, actual command arguments, exit codes, stdout/stderr, API responses,
final result and `SHA256SUMS.json`. Secret credential/token operations are
excluded from command transcripts. Evidence is explicitly marked
`production_acceptance=false`; it is not accepted as independent production
release proof. Ordinary CI uses mocks and never applies a real AWS lab.

For a diploma run, create a separate local report under `docs/local/` and add a
short caption to each **actual** screenshot. Capture:

| Stage | Console/menu evidence | AWS Console evidence |
| --- | --- | --- |
| Scope and plan | account/region, saved plan and review result | selected region, unique ECR name |
| First deployment A | apply, state/live digest, 2xx health, analysis response | Lambda image/configuration, API IAM route, request logs |
| Update B | changed digest and `/version` | Lambda code image digest |
| Failed C and recovery | exit 1, 503 response, B restored, healthy state/readback | recovered Lambda digest and logs |
| Manual rollback A | reviewed rollback, A active, health | Lambda digest |
| Finish | retained resources or reviewed cleanup result | inventory and later billing |

Record the source commit, CLI version, account/region, image digests, commands
and results. A local demo, mock test or transcript viewer must be labelled as
such. Screenshots supplement raw records; they do not replace health/digest
checks. Do not capture access tokens, keys or personal billing information.
Retain evidence independently before cleanup.

## Finish and cleanup

State/evidence are retained by default. Keeping a deployed lab can incur costs.
Use `lab plan diploma --stage destroy`, read its complete plan and apply that
exact plan/hash with `--yes` only after choosing what to preserve.

ECR force deletion and S3 force destruction remain disabled. Nonempty image
repositories or versioned buckets deliberately block destroy; do not remove
state to hide them. Follow [finish-demo](runbooks/finish-demo.md) to back up and
explicitly review data/image removal first. Keep rollback images until recovery
and manual rollback evidence are finished. Lab uses no shared state backend.
Destroy may schedule KMS deletion rather than immediately removing a key;
verify retained keys, logs, buckets, ECR, and delayed billing in AWS Console.
`destroyed` means Terraform state has no resources, not a promise of zero charges.
