locals {
  original_names = {
    for purpose in ["access-logs", "workload-data"] :
    purpose => "${var.name_prefix}-${purpose}-${var.account_id}"
  }
  bucket_names = {
    for purpose, name in local.original_names :
    purpose => (
      length(name) <= 63 && !can(regex("^(xn--|sthree-|amzn-s3-demo-)", name))
      ? name
      : "kit-${substr(name, 0, 42)}-${substr(sha256(name), 0, 16)}"
    )
  }
}

output "names" {
  description = "Stable S3 bucket names, preserving existing valid names."
  value       = local.bucket_names
}
