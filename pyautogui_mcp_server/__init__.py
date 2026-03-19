from .__info__ import (
    __author__,
    __description__,
    __issues__,
    __license__,
    __maintainer__,
    __url__,
    __version__,
)

__all__ = [
    "PythonInterpreterRuntime",
    "__author__",
    "__description__",
    "__issues__",
    "__license__",
    "__maintainer__",
    "__url__",
    "__version__",
]


def __getattr__(name: str):
    if name == "PythonInterpreterRuntime":
        from .runtime import PythonInterpreterRuntime

        return PythonInterpreterRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
