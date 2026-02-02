# MPComm Python package
# Note: The actual mpcomm module is compiled from C++ using pybind11

try:
    from mpcomm import (
        MPComm,
        MPCommError,
    )
    __all__ = ["MPComm", "MPCommError"]
except ImportError:
    # Module not built yet
    pass
