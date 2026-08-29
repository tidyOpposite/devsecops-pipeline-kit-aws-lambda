"""Canonical project paths owned or inspected by the CLI."""

from pathlib import Path


CONFIG_FILE = ".devsecops-pipeline.toml"
SETUP_STATE_FILE = Path(".devsecops/setup-state.json")
DEPLOYMENT_STATE_FILE = Path(".devsecops/deployments.json")
DIST_DIR = Path("dist/devsecops")
GENERATED_TFVARS = Path("terraform/generated.auto.tfvars")
AUDIT_REPORT = DIST_DIR / "audit-report.json"
RC_EVIDENCE_DIR = DIST_DIR / "evidence/rc"
PRODUCTION_EVIDENCE_DIR = DIST_DIR / "production-evidence"

REQUIRED_PROJECT_FILES = [
    "terraform/main.tf",
    "terraform/modules/lambda/main.tf",
    ".github/workflows/deploy.yml",
]

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
