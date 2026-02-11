rm -rf build

mkdir build
cd build

cmake .. \
    -DCMAKE_INSTALL_PREFIX=../mpcomm-install \
    -DUSE_MLNX=ON \
    -DUSE_CUDA=ON \
    -DBUILD_MPCOMM_PYTHON=ON

make -j$(nproc)
make install