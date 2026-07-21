# MPComm Python package
# Note: The actual mpcomm module is compiled from C++ using pybind11.
#       The compiled .so file (OUTPUT_NAME="mpcomm") lives alongside
#       this __init__.py inside the "mpcomm" package directory, so we
#       must use a *relative* import to avoid the package shadowing itself.

import os as _os

# ---- Package root directory ------------------------------------------------
_PACKAGE_DIR = _os.path.dirname(_os.path.abspath(__file__))

# ---- Version ---------------------------------------------------------------
try:
    from importlib.metadata import version as _get_version
    __version__ = _get_version("mpcomm")
except Exception:  # pylint: disable=broad-except
    # Version lookup is best-effort; any failure falls back to "unknown".
    __version__ = "unknown"

# ---- Python bindings -------------------------------------------------------
try:
    from .mpcomm import (  # noqa: F401  — relative import from the .so
        MPComm,
        MPCommError,
        INVALID_TRANSFER_HANDLE,
    )
except ImportError as _e:
    # If the .so file exists but fails to load (e.g. missing shared libs),
    # raise a clear error instead of silently swallowing it.
    import glob as _glob
    _so_files = _glob.glob(_os.path.join(_PACKAGE_DIR, "mpcomm*.so")) + \
                _glob.glob(_os.path.join(_PACKAGE_DIR, "mpcomm*.pyd"))
    if _so_files:
        raise ImportError(
            f"mpcomm C++ binding found ({_so_files[0]}) but failed to load: {_e}\n"
            f"Hint: run 'ldd {_so_files[0]}' to check for missing shared libraries."
        ) from _e
    # .so not built yet — this is fine (e.g. during sdist / development)
    pass

# ---- C++ SDK path helpers --------------------------------------------------
# When installed via `pip install`, the wheel bundles the full C++ SDK:
#   mpcomm/include/   — header files (mpcomm.h, mpcomm_log.h)
#   mpcomm/lib/       — libmpcomm.so, libmpcomm.a
#   mpcomm/lib/cmake/ — CMake package config files


def get_include_dir() -> str:
    """Return the path to the MPComm C++ header directory.

    Usage in a build script or CMakeLists.txt:
        include_directories($(python3 -c "import mpcomm; print(mpcomm.get_include_dir())"))
    """
    return _os.path.join(_PACKAGE_DIR, "include")


def get_lib_dir() -> str:
    """Return the path to the MPComm C++ library directory.

    Usage in a build script or CMakeLists.txt:
        link_directories($(python3 -c "import mpcomm; print(mpcomm.get_lib_dir())"))
    """
    return _os.path.join(_PACKAGE_DIR, "lib")


def get_cmake_dir() -> str:
    """Return the path to the MPComm CMake package config directory.

    Usage:
        cmake -Dmpcomm_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_cmake_dir())") ..
    """
    return _os.path.join(_PACKAGE_DIR, "lib", "cmake", "mpcomm")


def get_check_install_script() -> str:
    """Return the path to the check_install.sh verification script.

    Usage:
        bash $(python3 -c "import mpcomm; print(mpcomm.get_check_install_script())")
    """
    return _os.path.join(_PACKAGE_DIR, "scripts", "check_install.sh")


__all__ = [
    "MPComm",
    "MPCommError",
    "INVALID_TRANSFER_HANDLE",
    "__version__",
    "get_include_dir",
    "get_lib_dir",
    "get_cmake_dir",
    "get_check_install_script",
]
