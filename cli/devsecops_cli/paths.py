"""Find the caller's checkout without crossing another Git root."""

from pathlib import Path

REQUIRED_PROJECT_FILES = (
    "terraform/main.tf",
    "terraform/.terraform.lock.hcl",
    "terraform/modules/lambda/main.tf",
)


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if all((candidate / name).is_file() for name in REQUIRED_PROJECT_FILES):
            return candidate
        if (candidate / ".git").exists():
            break
    return current
