rm -rf build
mkdir -p build
cd build
cmake .. -DUSE_CUDA=ON -Dmpcomm_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_cmake_dir())" 2>/dev/null || echo "")
make -j$(nproc)
