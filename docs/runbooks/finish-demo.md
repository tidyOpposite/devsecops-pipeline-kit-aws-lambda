# Finish A Demo And Decommission Resources

Open this guide with `devsecops terraform teardown`, or from Deploy → Finish
demo / cleanup guide (also Advanced → Terraform). Opening it is local and
read-only. **This procedure is prepared for final acceptance; it has not yet
been executed against the final AWS account.**

If you only ran local demo setup and never deployed, it created no AWS
resources. Keep its local config/snapshots for the thesis or remove them
manually after archiving. Switching an existing deployment to demo mode does
not remove its cloud resources.

## 1. Choose What Must Survive

Record the owner, account, region, workspace, exact resource IDs, retention
decision, backup location and a successful restore/read test in `teardown.md`.
The owner approves this record before destructive steps. There are two outcomes:

* **Pause/retain:** stop traffic and writers, retain data, images and their keys.
  Keep their Terraform state. Storage/backup/key costs can continue. Do not run
  the full destroy plan while retained data still depends on its KMS key.
* **Decommission:** export required data outside the retiring stack, verify it
  is readable/restorable without the retiring key, then approve deletion of
  originals. Workload stacks go first. The shared backend stays by default;
  retiring it is a separate, final decision.

| Resource boundary | Preserve before deletion | Default decision |
| --- | --- | --- |
| Workload S3 data/access logs | Required current **and historical** versions, delete-marker inventory, readable restore sample | Keep until owner approves export/deletion |
| Built-in ECR | Needed image digests and a tested copy in an independent repository/archive | Keep until no workload needs those images |
| External/BYO ECR, app resources and custom DNS | Their owners' independent retention plan | Outside this stack; never infer permission to delete them |
| CloudWatch and SQS DLQ | Required log exports and workload-specific message recovery | Resolve before full stack destruction |
| Workload KMS key | Every retained ciphertext must remain decryptable independently | Retain if any dependency is unresolved |
| State bucket, state access logs, lock table, backend KMS | Every consumer/workspace state, bootstrap management state, necessary backups | Retain shared backend; delete last only if exclusively unused |

`aws s3 sync` is not an archive of historical versions or delete markers.
Choose a backup/export mechanism covering the versions you need, preserve its
inventory and test restoration. An archive still encrypted with the retiring
KMS key is not an independent backup. SQS recovery is workload-specific;
`ReceiveMessage` changes visibility and cannot prove a complete generic backup.

## 2. Freeze Changes, Confirm Scope And Preserve State

Run from the deployment checkout with the original reviewed config, generated
inputs and backend settings. Do not apply another preset or create a workspace
for cleanup. Use a decommission identity authorized for the chosen resources.

```bash
umask 077
export AWS_PAGER="" AWS_CLI_AUTO_PROMPT=off
: "${ACCOUNT_ID:?independently confirmed AWS account}"
: "${AWS_REGION:?reviewed workload region}"
: "${WORKSPACE:?existing Terraform workspace}"
: "${ENVIRONMENT:?environment recorded in that workspace state}"
: "${EVIDENCE_DIR:?absolute archive path outside retiring buckets and keys}"
case "${EVIDENCE_DIR}" in
  /*) ;;
  *) echo "Use an absolute EVIDENCE_DIR outside retiring resources." >&2; exit 1 ;;
esac
mkdir -p "${EVIDENCE_DIR}"
test "$(aws sts get-caller-identity --query Account --output text)" = "${ACCOUNT_ID}"
aws s3api head-bucket --bucket "${STATE_BUCKET:?reviewed backend bucket}" \
  --expected-bucket-owner "${ACCOUNT_ID}" --region "${BACKEND_REGION:?reviewed backend region}"
terraform -chdir=terraform init -reconfigure -input=false \
  -backend-config=../dist/devsecops/backend.hcl
terraform -chdir=terraform workspace list
terraform -chdir=terraform workspace select "${WORKSPACE}"
test "$(terraform -chdir=terraform workspace show)" = "${WORKSPACE}"
terraform -chdir=terraform state pull > "${EVIDENCE_DIR}/state-before.json"
terraform -chdir=terraform output -json > "${EVIDENCE_DIR}/outputs-before.json"
```

Review backend bucket/key/workspace prefix, state lineage/serial, project,
environment, region, resource ARNs and account against the deployment evidence.
The state name alone is not ownership evidence. Secure these files outside Git
and verify the archive survives removal of the stack. Keep original bootstrap
state too; a new empty bootstrap directory cannot manage existing resources.

Freeze workflow dispatches and other writers with the repository owner. For
example, disabling the deployment workflow is a GitHub mutation:

```bash
gh workflow disable deploy.yml --repo "${REPOSITORY:?reviewed deployment repository}"
gh run list --repo "${REPOSITORY}" --workflow deploy.yml --status in_progress
```

Wait for active apply/rollback runs and other state consumers to finish; do not
force-unlock active work. Record the previous workflow setting for pause/recovery.
Stop clients, scheduled jobs and external image/data consumers. After checking
the API ID/function name against state, these AWS mutations stop this kit's
HTTP stage and reserve zero Lambda concurrency, while keeping logs for export:

```bash
test "$(aws sts get-caller-identity --query Account --output text)" = "${ACCOUNT_ID}"
aws apigatewayv2 delete-stage --api-id "${API_ID:?reviewed state API ID}" \
  --stage-name '$default' --region "${AWS_REGION}"
aws lambda put-function-concurrency --function-name "${FUNCTION_NAME:?reviewed state Lambda name}" \
  --reserved-concurrent-executions 0 --region "${AWS_REGION}"
```

The API ID is in `module.api_gateway.aws_apigatewayv2_api.http_api`; use
`terraform state show` to review it. Verify traffic/writers have stopped and
wait for in-flight invocations. Pausing creates intentional Terraform drift:
do not re-enable deployments or run a normal apply during decommissioning.
For a pause that you later reverse, review a normal Terraform plan to restore
the stage and the configured concurrency; do not leave an undocumented outage.

After quiescing, capture `state pull` and `output -json` again as new
`state-quiesced.json` / `outputs-quiesced.json` artifacts. Reconcile any changes
since the first snapshot before selecting resources for deletion.

## 3. Review And Empty Workload Data

Finish the approved backups first, including CloudWatch log exports (wait for
export completion) and any DLQ messages. Stop workload data-bucket access-log
delivery before emptying its log destination:

```bash
aws s3api put-bucket-logging --bucket "${DATA_BUCKET:?reviewed workload bucket}" \
  --expected-bucket-owner "${ACCOUNT_ID}" --region "${AWS_REGION}" \
  --bucket-logging-status '{}'
```

Server access logs/in-flight uploads may arrive late. Each cleanup is bounded
to an explicitly reviewed inventory, not an endless delete-until-empty loop.
Create a **new** manifest for the data bucket, then repeat separately for the
workload log bucket with `--purpose workload-logs`:

```bash
devsecops terraform teardown bucket-plan \
  --bucket "${DATA_BUCKET}" --expected-account-id "${ACCOUNT_ID}" --region "${AWS_REGION}" \
  --purpose workload-data --output "${EVIDENCE_DIR}/data-bucket-plan.json" --format json
```

The manifest contains exact object versions, delete markers and multipart
upload IDs. Inspect every entry and the retention decision; record the printed
SHA-256 as `PLAN_SHA256`. The manifest is owner-only and never overwritten.
The identity needs STS access and the S3 reads for HeadBucket, bucket location,
versioning, versions and multipart inventories. Purge additionally needs
DeleteObjectVersion and AbortMultipartUpload; it needs neither DeleteBucket
nor governance-retention bypass permissions. The helper checks the actual
bucket region as well as expected ownership. Configured backend buckets cannot
be mislabeled as workload cleanup in the deployment checkout.
Only after owner approval, permanently delete those entries:

```bash
devsecops terraform teardown bucket-purge \
  --bucket "${DATA_BUCKET}" --expected-account-id "${ACCOUNT_ID}" --region "${AWS_REGION}" \
  --manifest "${EVIDENCE_DIR}/data-bucket-plan.json" --sha256 "${PLAN_SHA256:?reviewed manifest SHA-256}" \
  --acknowledge-backup --format json
```

The helper rechecks STS identity/expected bucket owner and the entire inventory
before mutation; plans expire after one hour. It deletes explicit version IDs
in batches of at most 1000, handles `null` versions and delete markers, aborts
approved uploads and verifies both inventories are empty. It never deletes the
bucket, ECR or keys. A changed inventory, access error, MFA Delete, partial
`DeleteObjects` failure, Object Lock refusal or remaining upload is a nonzero
result, not successful cleanup. Preserve state/key, resolve the cause and
review a new manifest. Retention/legal holds must not be bypassed. Large
inventories above 100000 entries/32 MiB require a separate reviewed bulk process.

These details matter because ordinary versioned-object deletion can leave
previous data and delete markers. See [S3 emptying](https://docs.aws.amazon.com/AmazonS3/latest/userguide/empty-bucket.html)
and [multipart abort](https://docs.aws.amazon.com/AmazonS3/latest/userguide/abort-mpu.html).

For the **built-in, exclusively retired** ECR repository, capture all image
digests using `aws ecr list-images --registry-id "$ACCOUNT_ID" --repository-name
"$ECR_REPOSITORY" --region "$AWS_REGION" --output json` (AWS CLI auto-pagination
must remain enabled). Copy required images to independent storage and verify a
pull first. Review the exact digest list. Delete approved digests with
`aws ecr batch-delete-image` and `--registry-id "$ACCOUNT_ID"`, in batches of at
most 100, checking the returned `failures` array after **every** call. For image
indexes, remove approved parent indexes before referenced child manifests.
Re-list and require an empty `imageIds` array. Do not use repository `--force`,
revoke ECR KMS grants, or delete a BYO/shared repository. Terraform will remove
the empty built-in repository in the next step.
[ECR image deletion](https://docs.aws.amazon.com/AmazonECR/latest/userguide/delete_image.html)
documents these API operations.

## 4. Destroy The Reviewed Workload Stack, One Workspace At A Time

The kit intentionally keeps S3 `force_destroy` and ECR `force_delete` disabled.
Create the destroy plan **after** backups/emptying and refreshing stopped resources.
The optional `expected_account_id` provider guard pins this operation to the
independently confirmed account; it does not change normal deployment defaults.

```bash
test "$(aws sts get-caller-identity --query Account --output text)" = "${ACCOUNT_ID}"
test "$(terraform -chdir=terraform workspace show)" = "${WORKSPACE}"
terraform -chdir=terraform plan -destroy -input=false -lock-timeout=5m \
  -var="expected_account_id=${ACCOUNT_ID}" -var="environment=${ENVIRONMENT}" \
  -out="${EVIDENCE_DIR}/workload-destroy.tfplan"
terraform -chdir=terraform show -json "${EVIDENCE_DIR}/workload-destroy.tfplan" \
  > "${EVIDENCE_DIR}/workload-destroy-plan.json"
terraform -chdir=terraform show -no-color "${EVIDENCE_DIR}/workload-destroy.tfplan"
```

Review **all** deletes: only this workspace's API, Lambda, IAM role/policy,
DLQ, CloudWatch groups, approved S3 buckets, built-in ECR and workload key.
Reject unexpected project/account/region resources, replacements/creates, or a
plan that includes anything still retained. The bootstrap backend must not be
part of this plan. Then require a target-specific confirmation:

```bash
read -r -p "Type destroy/${ACCOUNT_ID}/${WORKSPACE}: " CONFIRM
test "${CONFIRM}" = "destroy/${ACCOUNT_ID}/${WORKSPACE}" && \
  terraform -chdir=terraform apply -input=false "${EVIDENCE_DIR}/workload-destroy.tfplan"
```

Keep the apply log and final `state pull`; require no managed resources in that
workspace. If any operation fails, preserve the state/plan/logs and diagnose the
remaining resources. Do not remove state bindings, turn on force deletion or
delete the backend to conceal a failure. Re-plan from current state after repair.
Repeat for **every existing used workspace**, including `default` if it was
used with an environment fallback. Do not delete a nonempty workspace or create
a new one to obtain an empty result. The `default` workspace itself cannot be
deleted. Record each workspace's outcome separately.

KMS deletion is scheduled, not immediate: this kit configures seven days.
Verify `KeyState=PendingDeletion` and record the actual deletion date. It cannot
decrypt retained ciphertext during that interval. If retention was overlooked,
stop cleanup and follow [KMS cancellation](https://docs.aws.amazon.com/kms/latest/developerguide/deleting-keys-cancelling-key-deletion.html)
before the deadline; do not assume a new key can recover that data.

## 5. Retire The Backend Only If Exclusively Unused

**Default: keep it.** Enumerate every consumer, workspace and state key/prefix,
not just the three usual environment names. Other projects, sandbox plans and
old/manual states may still depend on the bucket, lock table or key. Review
archived states, application/data exports and all relevant decrypt dependencies.
Unknown/shared consumers mean **retain**, record ownership and continuing cost.

For an owner-approved exclusive backend retirement:

1. Finish all workload destroys; preserve final states and destroy evidence for
   each used workspace, plus all required historical state versions. Verify
   those archives are readable without the backend KMS key.
2. Keep the bootstrap management state outside the retiring backend. This kit's
   bootstrap normally uses local `terraform/bootstrap/terraform.tfstate`.
   If management state was moved into this backend, first migrate it to an
   independent backend/local protected state and verify all resources are still
   recorded. Follow [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3).
   Never destroy a backend while Terraform still needs it for its own state/lock.
3. Stop all state readers/writers and disable state-bucket access-log delivery
   with `put-bucket-logging --bucket-logging-status '{}'` and the expected owner.
   Allow late logging to settle. Repeat bucket plan/purge separately with
   `--purpose backend-state` and `--purpose backend-logs`, in their actual region.
   Backend purges additionally require `--allow-backend-cleanup`; the helper
   cannot establish that all other consumers have been retired for you.
4. In the **original/migrated** bootstrap root, plan `-destroy` with the original
   `state_bucket_name`, `state_log_bucket_name`, `lock_table_name`, `aws_region`
   and `-var="expected_account_id=${ACCOUNT_ID}"`. Save/review that plan and
   require the separate phrase `destroy-backend/ACCOUNT_ID/STATE_BUCKET` before
   applying it. It should remove only the approved empty state/log buckets,
   lock table, related policies and backend KMS key. Do not force-remove a lock.
5. Preserve final bootstrap state/logs and KMS schedule outside the deleted
   backend. Check for independent DynamoDB backups/recovery points and their
   retention decisions; deleting a table is not an instruction to erase backups.

## 6. Verify Leftovers And Close The Record

Check exact resource IDs in the confirmed account/region, not just tags. Empty
Terraform state is necessary but is not proof that no manually created/orphaned
resources remain. Only the service's explicit not-found response establishes
absence; access denied, timeout, wrong region or missing tools are **unverified**.

| Verify | Expected result or explicit retention record |
| --- | --- |
| API/Lambda/CloudWatch/SQS/IAM | Targeted resources absent; required logs/messages already exported |
| S3 | Each approved bucket absent, or retained with version/upload inventory and owner |
| ECR | Built-in repo absent; copied/BYO/shared images retained with owner and independent key |
| Workload and backend KMS | PendingDeletion with date, then final absence after the waiting period; retained keys listed |
| State backend | Intentionally retained, or all approved backend resources retired with independent state/evidence |
| Other resources | Custom DNS, external images, copied data, sandbox states, on-demand/PITR backups, log exports, subscriptions or unrelated infrastructure accounted for |
| GitHub access | Re-enable only retained deployments intentionally; remove unused deployment roles/secrets/trust only after cleanup no longer needs them |

Keep `teardown.md` with command results, manifest hashes, selected backup/restore
evidence, deleted/retained IDs, KMS dates, failures and next owner action. Use
`incomplete`, `paused/retained`, `removed with KMS deletion pending`, or
`verified removed`; do not label a scheduled key deletion or an access error
as complete zero-cost removal.

A stopped function does not erase retained S3 versions/uploads, ECR layers,
logs, backups or customer-managed keys. Review those explicitly and check
Billing/Cost Explorer again after its data refresh; immediate zero cost is not
a postcondition. [Cost Explorer refresh](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-enable.html)
is at least daily, and [KMS deletion](https://docs.aws.amazon.com/kms/latest/developerguide/deleting-keys.html)
has a waiting period. See [cost controls and retained resources](../cost-estimation.md).

## Final Acceptance Record

After all audit fixes, execute this procedure in the approved test account with
the owner's retention choices. Include: a retained-data restore test; at least
one current and noncurrent version, a delete marker and an incomplete upload;
an approved ECR image; successful per-workspace destroy; a deliberately retained
shared backend; a separately approved exclusive-backend retirement; partial
failure/retry evidence; and later KMS/billing verification. Attach results to
the production evidence bundle. Local tests and mocked Terraform teardown do
not substitute for this real-service acceptance.
