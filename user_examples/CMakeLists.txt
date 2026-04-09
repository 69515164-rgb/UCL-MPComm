cmake_minimum_required(VERSION 3.14)
project(mpcomm_scatter_test LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find installed mpcomm package
# User should set CMAKE_PREFIX_PATH to the mpcomm install directory, e.g.:
#   cmake .. -DCMAKE_PREFIX_PATH=/opt/mpcomm
find_package(mpcomm REQUIRED)

# Explicitly resolve mpcomm include directory via Python to work around
# potential _IMPORT_PREFIX mismatch in pip-installed wheels.
execute_process(
    COMMAND python3 -c "import mpcomm; print(mpcomm.get_include_dir())"
    OUTPUT_VARIABLE MPCOMM_INCLUDE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE _mpcomm_py_result
)
if(NOT _mpcomm_py_result EQUAL 0 OR NOT EXISTS "${MPCOMM_INCLUDE_DIR}")
    # Fallback: try to infer from mpcomm_DIR
    get_filename_component(_mpcomm_pkg_dir "${mpcomm_DIR}/../../.." ABSOLUTE)
    set(MPCOMM_INCLUDE_DIR "${_mpcomm_pkg_dir}/include")
endif()
message(STATUS "MPComm include dir: ${MPCOMM_INCLUDE_DIR}")

# Optional: CUDA support for HBM tests
option(USE_CUDA "Enable CUDA/GPU memory support" OFF)

# Find numa library (used directly in the test for DRAM allocation)
find_library(NUMA_LIBRARY numa REQUIRED)

# Build the scatter test executable
add_executable(scatter_test scatter_test.cpp)

target_link_libraries(scatter_test PRIVATE
    mpcomm::mpcomm    # shared library (recommended)
    ${NUMA_LIBRARY}   # for numa_alloc_onnode in test code
)

# Ensure mpcomm headers are found (supplements INTERFACE_INCLUDE_DIRECTORIES
# from mpcomm::mpcomm which may have incorrect prefix in pip-installed wheels)
target_include_directories(scatter_test PRIVATE ${MPCOMM_INCLUDE_DIR})

target_compile_options(scatter_test PRIVATE -Wall -Wextra -O2)

if(USE_CUDA)
    find_library(CUDA_DRIVER_LIBRARY cuda
        PATHS /usr/local/cuda/lib64 /usr/lib/x86_64-linux-gnu
        QUIET
    )
    find_path(CUDA_INCLUDE_DIR cuda.h
        PATHS /usr/local/cuda/include
        QUIET
    )
    if(CUDA_DRIVER_LIBRARY AND CUDA_INCLUDE_DIR)
        target_compile_definitions(scatter_test PRIVATE USE_CUDA)
        target_include_directories(scatter_test PRIVATE ${CUDA_INCLUDE_DIR})
        target_link_libraries(scatter_test PRIVATE ${CUDA_DRIVER_LIBRARY})
    else()
        message(WARNING "CUDA not found, HBM tests will be disabled")
    endif()
endif()
