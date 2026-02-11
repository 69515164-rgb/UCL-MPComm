rm -rf build
mkdir build && cd build
cmake .. -DUSE_CUDA=ON -DCMAKE_PREFIX_PATH=../mpcomm-install
make -j$(nproc) 
