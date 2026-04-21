#!/usr/bin/env bash
# ============================================================================
# MPComm one-click wheel build script
#
# Usage:
#   ./build_wheel.sh                    # default build
#   USE_MLNX=ON ./build_wheel.sh       # enable Mellanox support
#   USE_CUDA=ON ./build_wheel.sh       # enable CUDA support
#   USE_MLNX=ON USE_CUDA=ON ./build_wheel.sh  # both
#   USE_CUDA=ON USE_CUDA_KERNELS=ON ./build_wheel.sh  # build TMA H2D/D2H kernels (requires nvcc + Hopper)
#
# The resulting .whl file will be placed in the dist/ directory.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- configurable CMake options (via environment variables) ----------
USE_MLNX="${USE_MLNX:-ON}"
USE_BNXT="${USE_BNXT:-OFF}"
USE_CUDA="${USE_CUDA:-ON}"
# H2D/D2H TMA kernels are Hopper-only and require nvcc; enabled by default.
# Set USE_CUDA_KERNELS=OFF on build hosts without nvcc.
USE_CUDA_KERNELS="${USE_CUDA_KERNELS:-ON}"

echo "============================================"
echo " MPComm wheel builder"
echo "============================================"
echo " USE_MLNX         = $USE_MLNX"
echo " USE_BNXT         = $USE_BNXT"
echo " USE_CUDA         = $USE_CUDA"
echo " USE_CUDA_KERNELS = $USE_CUDA_KERNELS"
echo "============================================"

# ---------- detect package manager ------------------------------------------
install_packages() {
    if command -v apt-get &>/dev/null; then
        echo "[*] Detected Debian/Ubuntu (apt)"
        sudo apt-get update -qq
        sudo apt-get install -y -qq \
            build-essential cmake \
            libibverbs-dev \
            libnuma-dev \
            python3-dev python3-pip python3-venv

        if [ "$USE_MLNX" = "ON" ]; then
            sudo apt-get install -y -qq libmlx5-dev 2>/dev/null || \
                echo "[!] libmlx5-dev not found in apt, skipping (may already be installed via OFED)"
        fi

    elif command -v yum &>/dev/null; then
        echo "[*] Detected RHEL/CentOS (yum)"
        sudo yum install -y -q \
            gcc gcc-c++ cmake make \
            libibverbs-devel \
            numactl-devel \
            python3-devel python3-pip

        if [ "$USE_MLNX" = "ON" ]; then
            sudo yum install -y -q libmlx5-devel 2>/dev/null || \
                echo "[!] libmlx5-devel not found in yum, skipping (may already be installed via OFED)"
        fi

    elif command -v dnf &>/dev/null; then
        echo "[*] Detected Fedora/RHEL 9+ (dnf)"
        sudo dnf install -y -q \
            gcc gcc-c++ cmake make \
            libibverbs-devel \
            numactl-devel \
            python3-devel python3-pip

        if [ "$USE_MLNX" = "ON" ]; then
            sudo dnf install -y -q libmlx5-devel 2>/dev/null || \
                echo "[!] libmlx5-devel not found in dnf, skipping (may already be installed via OFED)"
        fi

    else
        echo "[!] Unsupported package manager. Please install the following manually:"
        echo "    - C++ compiler (g++ with C++17 support)"
        echo "    - CMake >= 3.15"
        echo "    - libibverbs development headers and libraries"
        echo "    - libnuma development headers and libraries"
        echo "    - Python 3 development headers"
        echo "    Then re-run this script."
        exit 1
    fi
}

# ---------- install system dependencies -------------------------------------
echo ""
echo "[1/4] Installing system dependencies..."
install_packages

# ---------- install Python build dependencies -------------------------------
echo ""
echo "[2/4] Installing Python build dependencies..."
pip3 install --upgrade pip
pip3 install build scikit-build-core pybind11

# ---------- sync version from VERSION file ----------------------------------
echo ""
echo "[3/4] Syncing version from VERSION file..."

# Fix Windows line endings (\r\n -> \n) that break TOML/CMake parsers
for f in pyproject.toml VERSION CMakeLists.txt; do
    if [ -f "$f" ]; then
        sed -i 's/\r$//' "$f"
    fi
done

# Parse VERSION file
MPCOMM_SEMVER=""
while IFS='=' read -r key value; do
    case "$key" in
        MPCOMM_VERSION) MPCOMM_VERSION_TAG="$value" ;;
        MPCOMM_SEMVER)  MPCOMM_SEMVER="$value" ;;
    esac
done < VERSION

if [ -z "$MPCOMM_SEMVER" ]; then
    echo "[!] ERROR: Failed to parse MPCOMM_SEMVER from VERSION file"
    exit 1
fi

echo "    Version tag : $MPCOMM_VERSION_TAG"
echo "    Semver      : $MPCOMM_SEMVER"

# Update pyproject.toml version in-place
sed -i "s/^version = \".*\"/version = \"${MPCOMM_SEMVER}\"/" pyproject.toml

# ---------- build wheel -----------------------------------------------------
echo ""
echo "[4/4] Building wheel..."

# Clean previous builds
rm -rf dist/ build/

# Assemble cmake.define overrides
CMAKE_ARGS=""
CMAKE_ARGS="$CMAKE_ARGS --config-setting=cmake.define.USE_MLNX=$USE_MLNX"
CMAKE_ARGS="$CMAKE_ARGS --config-setting=cmake.define.USE_BNXT=$USE_BNXT"
CMAKE_ARGS="$CMAKE_ARGS --config-setting=cmake.define.USE_CUDA=$USE_CUDA"
CMAKE_ARGS="$CMAKE_ARGS --config-setting=cmake.define.USE_CUDA_KERNELS=$USE_CUDA_KERNELS"

python3 -m build --wheel $CMAKE_ARGS

echo ""
echo "============================================"
echo " Build complete!"
echo " Wheel package:"
ls -lh dist/*.whl
echo ""
echo " Install with:"
echo "   pip install dist/mpcomm-*.whl"
echo "============================================"
