rm -rf build
mkdir build && cd build
cmake .. -DUSE_CUDA=ON -DCMAKE_PREFIX_PATH=/root/cheengguo/mpcomm/mpcomm-install
make -j$(nproc) 
