#!/usr/bin/env bash
# ============================================================================
# MPComm Test Files Deployment Script
#
# Downloads scatter_test source files from the Tencent mirror and builds
# the scatter_test binary locally. Test files are stored independently
# from the pip package directory.
#
# Usage:
#   bash deploy_tests.sh                    # default (release)
#   bash deploy_tests.sh --debug            # debug build
#   bash deploy_tests.sh --install-dir /opt/mpcomm_tests
#
#   # via pipe:
#   wget -qO- <URL>/deploy_tests.sh | bash
#   wget -qO- <URL>/deploy_tests.sh | bash -s -- --debug
#
# Exit code: 0 = success, 1 = failure
# ============================================================================
set -euo pipefail

# ------------------------------------------------------------------
# Parse arguments
# ------------------------------------------------------------------
DEBUG_BUILD=false
INSTALL_DIR="/opt/mpcomm_tests"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug)            DEBUG_BUILD=true; shift ;;
        --install-dir=*)    INSTALL_DIR="${1#*=}"; shift ;;
        --install-dir)      INSTALL_DIR="$2"; shift 2 ;;
        *)                  shift ;;
    esac
done

# Base URL for test files on Tencent mirror
TESTS_BASE_URL="https://mirrors.tencent.com/repository/generic/mpcomm/tests"

# Files to download
TEST_FILES=(
    "scatter_test.cpp"
    "CMakeLists.txt"
    "cpp-target.sh"
    "cpp-initiator.sh"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "============================================"
if $DEBUG_BUILD; then
    echo " MPComm Test Files Deployment (DEBUG)"
else
    echo " MPComm Test Files Deployment"
fi
echo "============================================"
echo "  Install dir: $INSTALL_DIR"
echo ""

# ------------------------------------------------------------------
# 1. Check prerequisites
# ------------------------------------------------------------------
info "Checking prerequisites..."

if [[ "$(uname -s)" != "Linux" ]]; then
    error "This script only supports Linux. Detected: $(uname -s)"
    exit 1
fi

ARCH=$(uname -m)
if [[ "$ARCH" != "x86_64" ]]; then
    error "This script requires x86_64 architecture. Detected: $ARCH"
    exit 1
fi

# Check Python (needed for mpcomm cmake dir resolution)
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    error "Python not found. mpcomm must be installed first (run deploy_mpcomm.sh)."
    exit 1
fi

# Verify mpcomm is installed
if ! "$PYTHON_CMD" -c "import mpcomm" 2>/dev/null; then
    error "mpcomm Python package not found. Install it first with deploy_mpcomm.sh."
    exit 1
fi

MPCOMM_VER=$("$PYTHON_CMD" -c "import mpcomm; print(mpcomm.__version__)" 2>/dev/null || echo "unknown")
info "mpcomm version: $MPCOMM_VER ✅"

# Check download tool
DL_CMD=""
if command -v wget &>/dev/null; then
    DL_CMD="wget"
elif command -v curl &>/dev/null; then
    DL_CMD="curl"
else
    error "Neither wget nor curl found. Please install one of them."
    exit 1
fi
info "Download tool: $DL_CMD ✅"

# ------------------------------------------------------------------
# 2. Download test files
# ------------------------------------------------------------------
echo ""
info "Downloading test files to $INSTALL_DIR ..."

mkdir -p "$INSTALL_DIR"

DOWNLOAD_FAIL=false
for f in "${TEST_FILES[@]}"; do
    info "  Downloading $f ..."
    if [[ "$DL_CMD" == "wget" ]]; then
        wget -q -O "$INSTALL_DIR/$f" "$TESTS_BASE_URL/$f" || {
            error "  Failed to download $f"
            DOWNLOAD_FAIL=true
            continue
        }
    else
        curl -fsSL -o "$INSTALL_DIR/$f" "$TESTS_BASE_URL/$f" || {
            error "  Failed to download $f"
            DOWNLOAD_FAIL=true
            continue
        }
    fi
done

if $DOWNLOAD_FAIL; then
    error "Some files failed to download. Aborting."
    exit 1
fi

# Make shell scripts executable
chmod +x "$INSTALL_DIR/cpp-target.sh" "$INSTALL_DIR/cpp-initiator.sh" 2>/dev/null || true

info "All test files downloaded ✅"

# ------------------------------------------------------------------
# 3. Install build dependencies if missing
# ------------------------------------------------------------------
echo ""
info "Checking build dependencies..."

DEPS_NEEDED=false
for pkg in cmake make g++; do
    if ! command -v "$pkg" &>/dev/null; then
        DEPS_NEEDED=true
        break
    fi
done
if ! dpkg -s libnuma-dev >/dev/null 2>&1; then
    DEPS_NEEDED=true
fi

if $DEPS_NEEDED; then
    info "Installing build dependencies..."
    apt-get update -qq && apt-get install -y -qq libnuma-dev cmake build-essential 2>&1 || {
        warn "Dependency install had issues (continuing anyway)"
    }
fi
info "Build dependencies ready ✅"

# ------------------------------------------------------------------
# 4. Build scatter_test
# ------------------------------------------------------------------
echo ""
info "Building scatter_test ..."

CMAKE_DIR=$("$PYTHON_CMD" -c "import mpcomm; print(mpcomm.get_cmake_dir())" 2>/dev/null || echo "")
if [[ -z "$CMAKE_DIR" ]]; then
    CMAKE_DIR=$("$PYTHON_CMD" -c "import mpcomm, os; print(os.path.join(os.path.dirname(mpcomm.__file__), 'lib', 'cmake', 'mpcomm'))" 2>/dev/null || echo "")
fi

if [[ -z "$CMAKE_DIR" ]]; then
    error "Cannot resolve mpcomm CMake directory. Is mpcomm installed correctly?"
    exit 1
fi
info "mpcomm CMake dir: $CMAKE_DIR"

BUILD_DIR="$INSTALL_DIR/build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

CMAKE_OK=false
cmake -S "$INSTALL_DIR" -B "$BUILD_DIR" \
    -Dmpcomm_DIR="$CMAKE_DIR" \
    -DUSE_CUDA=ON 2>&1 && CMAKE_OK=true

if $CMAKE_OK; then
    BUILD_OK=false
    make -C "$BUILD_DIR" -j"$(nproc)" VERBOSE=1 2>&1 && BUILD_OK=true

    if $BUILD_OK && [[ -x "$BUILD_DIR/scatter_test" ]]; then
        info "scatter_test built successfully ✅"
        info "Binary: $BUILD_DIR/scatter_test"
    else
        error "scatter_test build (make) failed."
        error "You can retry manually:"
        echo "    cd $BUILD_DIR && make VERBOSE=1"
        exit 1
    fi
else
    error "scatter_test cmake configure failed."
    error "You can retry manually:"
    echo "    cmake -S $INSTALL_DIR -B $BUILD_DIR -Dmpcomm_DIR=$CMAKE_DIR -DUSE_CUDA=ON"
    exit 1
fi

echo ""
echo "============================================"
echo -e " ${GREEN}✅ MPComm test files deployment complete!${NC}"
echo "============================================"
echo ""
echo "  Test dir:    $INSTALL_DIR"
echo "  Binary:      $BUILD_DIR/scatter_test"
echo "  Run:         $BUILD_DIR/scatter_test --help"
echo ""
