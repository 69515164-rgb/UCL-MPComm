rm -rf build
mkdir -p build
cd build
cmake .. -DUSE_CUDA=ON -DCMAKE_PREFIX_PATH=../mpcomm-install
make -j$(nproc)
