"""DevSecOps Pipeline Kit CLI package."""

from importlib import import_module

VERSION = "0.13.0"
__version__ = VERSION

__all__ = ["VERSION", "__version__", "main"]


def __getattr__(name: str):
    if name == "main":
        return import_module(".main", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
