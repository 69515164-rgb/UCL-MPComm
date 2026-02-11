# MPComm Python package
# Note: The actual mpcomm module is compiled from C++ using pybind11.
#       The compiled .so file (OUTPUT_NAME="mpcomm") lives alongside
#       this __init__.py inside the "mpcomm" package directory, so we
#       must use a *relative* import to avoid the package shadowing itself.

try:
    from .mpcomm import (  # noqa: F401  — relative import from the .so
        MPComm,
        MPCommError,
        INVALID_TRANSFER_HANDLE,
    )
    __all__ = ["MPComm", "MPCommError", "INVALID_TRANSFER_HANDLE"]
except ImportError:
    # Module not built yet
    pass
