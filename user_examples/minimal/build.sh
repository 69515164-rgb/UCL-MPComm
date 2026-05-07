#!/usr/bin/env bash
# Build the minimal C++ demo (hello_mpcomm).
# Uses the pip-installed mpcomm wheel for CMake config + headers.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
BUILD_DIR="${SCRIPT_DIR}/build"

mpcomm_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_cmake_dir())")
echo "Using mpcomm_DIR=${mpcomm_DIR}"

rm -rf "${BUILD_DIR}"
cmake -S "${SCRIPT_DIR}" -B "${BUILD_DIR}" -Dmpcomm_DIR="${mpcomm_DIR}"
cmake --build "${BUILD_DIR}" -j

echo "Built: ${BUILD_DIR}/hello_mpcomm"
