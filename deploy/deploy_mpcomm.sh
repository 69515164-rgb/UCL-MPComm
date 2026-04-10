#!/usr/bin/env bash
# ============================================================================
# MPComm one-click deployment script
#
# Downloads and installs mpcomm from the Tencent mirror.
# Performs environment checks before installation.
#
# Usage:
#   bash deploy.sh              # install release build
#   bash deploy.sh --debug       # install debug build
#
#   # via pipe:
#   wget -qO- <URL>/deploy_mpcomm.sh | bash
#   wget -qO- <URL>/deploy_mpcomm.sh | bash -s -- --debug
#
# Exit code: 0 = success, 1 = failure
# ============================================================================
set -euo pipefail

# ------------------------------------------------------------------
# Parse arguments
# ------------------------------------------------------------------
DEBUG_BUILD=false
for arg in "$@"; do
    case "$arg" in
        --debug) DEBUG_BUILD=true ;;
    esac
done

# Supported Python versions (add new versions here)
SUPPORTED_PYTHON_VERSIONS=("3.12" "3.13")

# Wheel URL/name will be determined after Python version detection (see section 3)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "============================================"
if $DEBUG_BUILD; then
    echo " MPComm One-Click Deployment (DEBUG)"
else
    echo " MPComm One-Click Deployment"
fi
echo "============================================"
echo ""

# ------------------------------------------------------------------
# 1. Check OS
# ------------------------------------------------------------------
info "Checking operating system..."
if [[ "$(uname -s)" != "Linux" ]]; then
    error "This script only supports Linux. Detected: $(uname -s)"
    exit 1
fi
info "OS: Linux ✅"

# ------------------------------------------------------------------
# 2. Check architecture
# ------------------------------------------------------------------
info "Checking CPU architecture..."
ARCH=$(uname -m)
if [[ "$ARCH" != "x86_64" ]]; then
    error "This wheel requires x86_64 architecture. Detected: $ARCH"
    exit 1
fi
info "Architecture: x86_64 ✅"

# ------------------------------------------------------------------
# 3. Check Python
# ------------------------------------------------------------------
info "Checking Python..."

# Find a usable python command
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    error "Python not found. Please install one of the supported versions: ${SUPPORTED_PYTHON_VERSIONS[*]}"
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
PYTHON_MAJOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.minor)")

info "Found Python $PYTHON_VERSION ($PYTHON_CMD)"

# Check if the detected Python version is supported
PY_TAG="cp${PYTHON_MAJOR}${PYTHON_MINOR}"
PY_SHORT="${PYTHON_MAJOR}.${PYTHON_MINOR}"
VERSION_SUPPORTED=false
for v in "${SUPPORTED_PYTHON_VERSIONS[@]}"; do
    if [[ "$PY_SHORT" == "$v" ]]; then
        VERSION_SUPPORTED=true
        break
    fi
done

if ! $VERSION_SUPPORTED; then
    error "Python $PY_SHORT is not supported. Supported versions: ${SUPPORTED_PYTHON_VERSIONS[*]}"
    echo ""
    echo "  Hint: Install a supported Python version via:"
    for v in "${SUPPORTED_PYTHON_VERSIONS[@]}"; do
        echo "    - pyenv install $v && pyenv global $v"
    done
    exit 1
fi
info "Python version: $PYTHON_VERSION ($PY_TAG) ✅"

# Build wheel URL and filename based on detected Python version
MPCOMM_VER="1.2.0"
WHL_NAME="mpcomm-${MPCOMM_VER}-${PY_TAG}-${PY_TAG}-linux_x86_64.whl"
if $DEBUG_BUILD; then
    WHL_URL="https://mirrors.tencent.com/repository/generic/mpcomm/build/debug/${WHL_NAME}"
else
    WHL_URL="https://mirrors.tencent.com/repository/generic/mpcomm/build/${WHL_NAME}"
fi
info "Wheel: $WHL_NAME"

# ------------------------------------------------------------------
# 4. Check pip
# ------------------------------------------------------------------
info "Checking pip..."
if ! "$PYTHON_CMD" -m pip --version &>/dev/null; then
    error "pip is not available. Please install pip first:"
    echo "    $PYTHON_CMD -m ensurepip --upgrade"
    exit 1
fi
PIP_VERSION=$("$PYTHON_CMD" -m pip --version | awk '{print $2}')
info "pip version: $PIP_VERSION ✅"

# ------------------------------------------------------------------
# 5. Check download tool
# ------------------------------------------------------------------
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
# 6. Download wheel
# ------------------------------------------------------------------
echo ""
info "Downloading $WHL_NAME ..."

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

if [[ "$DL_CMD" == "wget" ]]; then
    wget -q --show-progress -O "$TMPDIR/$WHL_NAME" "$WHL_URL"
else
    curl -fL --progress-bar -o "$TMPDIR/$WHL_NAME" "$WHL_URL"
fi

if [[ ! -f "$TMPDIR/$WHL_NAME" ]]; then
    error "Download failed."
    exit 1
fi

FILE_SIZE=$(stat --printf="%s" "$TMPDIR/$WHL_NAME" 2>/dev/null || stat -f%z "$TMPDIR/$WHL_NAME" 2>/dev/null)
info "Downloaded successfully ($(( FILE_SIZE / 1024 )) KB)"

# ------------------------------------------------------------------
# 7. Install
# ------------------------------------------------------------------
echo ""
info "Installing mpcomm..."
"$PYTHON_CMD" -m pip install --force-reinstall "$TMPDIR/$WHL_NAME"

if [[ $? -ne 0 ]]; then
    error "Installation failed."
    exit 1
fi

# ------------------------------------------------------------------
# 8. Verify
# ------------------------------------------------------------------
echo ""
info "Verifying installation..."
INSTALLED_VERSION=$("$PYTHON_CMD" -c "import mpcomm; print(mpcomm.__version__)" 2>/dev/null || echo "")

if [[ -n "$INSTALLED_VERSION" && "$INSTALLED_VERSION" != "unknown" ]]; then
    info "mpcomm $INSTALLED_VERSION installed successfully ✅"
else
    warn "mpcomm installed but version could not be determined"
fi

echo ""
echo "============================================"
echo -e " ${GREEN}✅ MPComm deployment complete!${NC}"
echo "============================================"
echo ""
echo "  Quick test:  python3 -c 'from mpcomm import MPComm; print(\"OK\")'"
echo ""
echo "  Full check:  bash \$(python3 -c 'import mpcomm; print(mpcomm.get_check_install_script())')"
echo ""
