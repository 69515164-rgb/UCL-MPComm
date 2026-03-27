#!/usr/bin/env bash
# ============================================================================
# MPComm deployment verification script
#
# Checks whether the mpcomm package is correctly installed without
# requiring RDMA hardware or network connectivity.
#
# Usage:
#   ./check_install.sh
#
# Exit code: 0 = all checks passed, 1 = one or more checks failed
# ============================================================================
set -uo pipefail

PASS=0
FAIL=0
WARN=0

pass() { echo "  ✅ $1"; ((PASS++)); }
fail() { echo "  ❌ $1"; ((FAIL++)); }
warn() { echo "  ⚠️  $1"; ((WARN++)); }

echo "============================================"
echo " MPComm Deployment Check"
echo "============================================"
echo ""

# ------------------------------------------------------------------
# 1. Python module import
# ------------------------------------------------------------------
echo "[1/5] Python module import"
if python3 -c "import mpcomm" 2>/dev/null; then
    pass "import mpcomm OK"
else
    fail "import mpcomm FAILED (module not found)"
    echo ""
    echo "❌ Cannot proceed without mpcomm module. Install it first:"
    echo "   pip install mpcomm-*.whl"
    exit 1
fi

# ------------------------------------------------------------------
# 2. Version
# ------------------------------------------------------------------
echo ""
echo "[2/5] Version info"
VERSION=$(python3 -c "import mpcomm; print(mpcomm.__version__)" 2>/dev/null)
if [ -n "$VERSION" ] && [ "$VERSION" != "unknown" ]; then
    pass "version = $VERSION"
else
    warn "version is unknown (metadata may be missing)"
fi

# ------------------------------------------------------------------
# 3. Core exports (classes, enums, constants)
# ------------------------------------------------------------------
echo ""
echo "[3/5] Core exports"

# First, check if the C++ .so binding actually loads
SO_IMPORT_ERR=$(python3 -c "
import importlib, mpcomm, os
pkg = os.path.dirname(mpcomm.__file__)
try:
    from mpcomm.mpcomm import MPComm
    print('')
except ImportError as e:
    print(str(e))
" 2>&1)

if [ -n "$SO_IMPORT_ERR" ]; then
    fail "C++ binding (.so) failed to load"
    echo "    Error: $SO_IMPORT_ERR"
    echo ""
    echo "    Diagnosing shared library dependencies..."
    PKG_DIR=$(python3 -c "import mpcomm, os; print(os.path.dirname(mpcomm.__file__))" 2>/dev/null)
    SO_PATH=$(find "$PKG_DIR" -maxdepth 1 -name "mpcomm.cpython*.so" 2>/dev/null | head -1)
    if [ -n "$SO_PATH" ]; then
        echo "    ldd $SO_PATH:"
        ldd "$SO_PATH" 2>&1 | grep -E "not found|=>" | sed 's/^/      /'
    fi
    echo ""
else
    pass "C++ binding (.so) loaded OK"
fi

python3 -c "from mpcomm import MPComm" 2>/dev/null \
    && pass "MPComm class available" \
    || fail "MPComm class NOT available"

python3 -c "from mpcomm import MPCommError; assert MPCommError.SUCCESS.value == 0" 2>/dev/null \
    && pass "MPCommError enum available (SUCCESS=0)" \
    || fail "MPCommError enum NOT available"

python3 -c "from mpcomm import INVALID_TRANSFER_HANDLE; assert INVALID_TRANSFER_HANDLE == 0" 2>/dev/null \
    && pass "INVALID_TRANSFER_HANDLE constant available" \
    || fail "INVALID_TRANSFER_HANDLE constant NOT available"

# Quick sanity: MPComm object can be instantiated
python3 -c "from mpcomm import MPComm; MPComm()" 2>/dev/null \
    && pass "MPComm() instantiation OK" \
    || fail "MPComm() instantiation FAILED"

# ------------------------------------------------------------------
# 4. C++ SDK files (headers + libraries)
# ------------------------------------------------------------------
echo ""
echo "[4/5] C++ SDK files"

INC_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_include_dir())" 2>/dev/null)
LIB_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_lib_dir())" 2>/dev/null)
CMAKE_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_cmake_dir())" 2>/dev/null)

# Headers
for header in mpcomm.h mpcomm_log.h; do
    if [ -f "$INC_DIR/$header" ]; then
        pass "$header found  ($INC_DIR/$header)"
    else
        fail "$header MISSING ($INC_DIR/$header)"
    fi
done

# Libraries
for lib in libmpcomm.so libmpcomm.a; do
    if [ -f "$LIB_DIR/$lib" ]; then
        pass "$lib found  ($LIB_DIR/$lib)"
    else
        fail "$lib MISSING ($LIB_DIR/$lib)"
    fi
done

# CMake config
if [ -d "$CMAKE_DIR" ]; then
    pass "CMake config dir exists ($CMAKE_DIR)"
else
    warn "CMake config dir missing ($CMAKE_DIR)"
fi

# ------------------------------------------------------------------
# 5. Python binding (.so) and dependencies
# ------------------------------------------------------------------
echo ""
echo "[5/5] Python binding (.so)"

PKG_DIR=$(python3 -c "import mpcomm, os; print(os.path.dirname(mpcomm.__file__))" 2>/dev/null)
SO_FILE=$(find "$PKG_DIR" -maxdepth 1 -name "mpcomm*.so" -o -name "mpcomm*.pyd" 2>/dev/null | head -1)

if [ -n "$SO_FILE" ]; then
    pass "binding found ($SO_FILE)"

    # Check for missing shared library dependencies
    if command -v ldd &>/dev/null; then
        MISSING=$(ldd "$SO_FILE" 2>/dev/null | grep "not found")
        if [ -n "$MISSING" ]; then
            fail "binding has missing dependencies:"
            echo "$MISSING" | sed 's/^/      /'
        else
            pass "all shared library dependencies satisfied"
        fi
    fi
else
    fail "binding .so NOT found in $PKG_DIR"
fi
# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo ""
echo "============================================"
echo " Results:  ✅ $PASS passed,  ❌ $FAIL failed,  ⚠️  $WARN warnings"
echo "============================================"

if [ "$FAIL" -gt 0 ]; then
    echo " ❌ Deployment check FAILED"
    exit 1
else
    echo " ✅ MPComm is correctly deployed!"
    exit 0
fi
