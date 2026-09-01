"""Public package interface for the DevSecOps Pipeline Kit CLI.

Only lightweight version metadata is imported eagerly.  The command module is
loaded on demand so library consumers can import domain helpers without also
initializing the comparatively large CLI orchestration layer.
"""

from importlib import import_module

VERSION = "0.13.1"
__version__ = VERSION

__all__ = ["VERSION", "__version__", "main"]


def __getattr__(name: str):
    """Lazily expose the command module as ``devsecops_cli.main``.

    Keeping this compatibility attribute lazy prevents the package initializer
    from becoming a dependency hub for modules that import :data:`VERSION`.
    """

    if name == "main":
        return import_module(".main", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
