rm -rf build
mkdir -p build
cd build

PYTHON_BIN="${PYTHON_BIN:-$(which python3)}"
CMAKE_MPCOMM_DIR="$(${PYTHON_BIN} -c "import mpcomm; print(mpcomm.get_cmake_dir())" 2>/dev/null || echo "")"

cmake .. \
  -DUSE_CUDA=ON \
  -DPython3_EXECUTABLE="${PYTHON_BIN}" \
  -Dmpcomm_DIR="${CMAKE_MPCOMM_DIR}"

make -j$(nproc)
