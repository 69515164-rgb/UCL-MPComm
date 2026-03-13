rm -rf build

mkdir build
cd build

cmake .. \
    -DCMAKE_INSTALL_PREFIX=../mpcomm-install \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DUSE_MLNX=ON \
    -DUSE_CUDA=ON \
    -DBUILD_MPCOMM_PYTHON=ON \
    -DPython3_EXECUTABLE=$(which python3)

make -j$(nproc)
make install