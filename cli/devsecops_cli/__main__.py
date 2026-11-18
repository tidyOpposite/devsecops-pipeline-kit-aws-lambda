"""Module entry point for ``python -m devsecops_cli``."""

from .main import main


if __name__ == "__main__":
    # Convert the CLI's integer result into the process status observed by
    # shells and automation, just like the installed ``devsecops`` command.
    raise SystemExit(main())
