"""Canonical project paths owned or inspected by the CLI.

Keeping paths in one dependency-free module gives generators, diagnostics, and
snapshot recovery the same ownership boundary.
"""

from pathlib import Path


# Local source and resumable runtime state.  Runtime JSON files contain only
# workflow metadata; credentials remain in AWS, GitHub, or process environment.
CONFIG_FILE = ".devsecops-pipeline.toml"
SETUP_STATE_FILE = Path(".devsecops/setup-state.json")
DEPLOYMENT_STATE_FILE = Path(".devsecops/deployments.json")
# CLI-owned generated artifacts and evidence outputs.
DIST_DIR = Path("dist/devsecops")
GENERATED_TFVARS = Path("terraform/generated.auto.tfvars")
AUDIT_REPORT = DIST_DIR / "audit-report.json"
RC_EVIDENCE_DIR = DIST_DIR / "evidence/rc"
PRODUCTION_EVIDENCE_DIR = DIST_DIR / "production-evidence"

# These representative source files distinguish a usable project checkout from
# an installed CLI running in an unrelated or incomplete directory.
REQUIRED_PROJECT_FILES = [
    "terraform/main.tf",
    "terraform/modules/lambda/main.tf",
    ".github/workflows/deploy.yml",
]

# Snapshot recovery is allowlisted: only source config and regenerated local
# artifacts may be captured or restored, never Terraform state or cloud data.
SNAPSHOT_DIR = Path(".devsecops/snapshots")
SNAPSHOT_FILES = [
    Path(CONFIG_FILE),
    GENERATED_TFVARS,
    DIST_DIR / "backend.tf",
    DIST_DIR / "github-variables.env",
    DIST_DIR / "github-setup.sh",
    DIST_DIR / "setup-checklist.md",
    DIST_DIR / "readiness-report.md",
    AUDIT_REPORT,
]
SNAPSHOT_FILE_PATHS = frozenset(str(path) for path in SNAPSHOT_FILES)

GENERATED_ARTIFACT_DOC = "docs/generated-artifacts.md"


__all__ = [
    "AUDIT_REPORT",
    "CONFIG_FILE",
    "DEPLOYMENT_STATE_FILE",
    "DIST_DIR",
    "GENERATED_ARTIFACT_DOC",
    "GENERATED_TFVARS",
    "PRODUCTION_EVIDENCE_DIR",
    "RC_EVIDENCE_DIR",
    "REQUIRED_PROJECT_FILES",
    "SNAPSHOT_DIR",
    "SNAPSHOT_FILES",
    "SNAPSHOT_FILE_PATHS",
    "SETUP_STATE_FILE",
]
