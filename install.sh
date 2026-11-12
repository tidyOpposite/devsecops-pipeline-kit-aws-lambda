#!/bin/sh
# Install this checkout into a new virtual environment; keep Terraform beside it.
set -eu
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON:-python3}
VENV_DIR="$SOURCE_DIR/.venv"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --python|--venv)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        printf '%s\n' "Missing value for $1" >&2
        exit 2
      fi
      case "$1" in
        --python) PYTHON_BIN=$2 ;;
        --venv) VENV_DIR=$2 ;;
      esac
      shift 2
      ;;
    --help|-h)
      printf '%s\n' 'Install the current checkout: sh install.sh [--python PATH] [--venv NEW_DIRECTORY]' 'Requires Python 3.11–3.14. Existing destinations are never overwritten.'
      exit 0
      ;;
    *) printf '%s\n' "Unknown option: $1" >&2; exit 2 ;;
  esac
done
"$PYTHON_BIN" -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 15), "Python 3.11–3.14 is required"'
if [ -e "$VENV_DIR" ] || [ -L "$VENV_DIR" ]; then
  printf '%s\n' "Destination already exists: $VENV_DIR. Choose a new directory." >&2
  exit 1
fi
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --no-deps "$SOURCE_DIR"
"$VENV_DIR/bin/devsecops" --version
printf '%s\n' "Installed: $VENV_DIR/bin/devsecops" "Keep this checkout for Terraform. Start with: $VENV_DIR/bin/devsecops --help"
