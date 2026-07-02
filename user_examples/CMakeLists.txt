cmake_minimum_required(VERSION 3.14)
project(mpcomm_scatter_test LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Optional: CUDA support for HBM tests
option(USE_CUDA "Enable CUDA/GPU memory support" OFF)

# Find numa library (used directly in the test for DRAM allocation)
find_library(NUMA_LIBRARY numa REQUIRED)

# Prefer resolving the pip-installed package via Python helper functions.
# This avoids a known issue where the wheel-exported CMake target may point
# INTERFACE_INCLUDE_DIRECTORIES at <site-packages>/include instead of the real
# <site-packages>/mpcomm/include path.
find_package(Python3 COMPONENTS Interpreter QUIET)

set(MPCOMM_INCLUDE_DIR "")
set(MPCOMM_LIB_DIR "")
set(MPCOMM_CMAKE_DIR "")
set(_MPCOMM_LINK_TARGET "mpcomm::mpcomm")

if(Python3_Interpreter_FOUND)
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -c "import mpcomm; print(mpcomm.get_include_dir()); print(mpcomm.get_lib_dir()); print(mpcomm.get_cmake_dir())"
        OUTPUT_VARIABLE _mpcomm_paths
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE _mpcomm_py_result
        ERROR_QUIET
    )
    if(_mpcomm_py_result EQUAL 0)
        string(REPLACE "\n" ";" _mpcomm_paths_list "${_mpcomm_paths}")
        list(LENGTH _mpcomm_paths_list _mpcomm_paths_count)
        if(_mpcomm_paths_count GREATER 0)
            list(GET _mpcomm_paths_list 0 MPCOMM_INCLUDE_DIR)
        endif()
        if(_mpcomm_paths_count GREATER 1)
            list(GET _mpcomm_paths_list 1 MPCOMM_LIB_DIR)
        endif()
        if(_mpcomm_paths_count GREATER 2)
            list(GET _mpcomm_paths_list 2 MPCOMM_CMAKE_DIR)
        endif()
    endif()
endif()

# Respect an explicit -Dmpcomm_DIR=... passed in from the command line, but if
# none was provided and Python helper functions succeeded, reuse that CMake dir.
if((NOT DEFINED mpcomm_DIR OR NOT mpcomm_DIR) AND MPCOMM_CMAKE_DIR)
    set(mpcomm_DIR "${MPCOMM_CMAKE_DIR}")
endif()

# Find installed mpcomm package.
if(DEFINED mpcomm_DIR AND mpcomm_DIR)
    find_package(mpcomm REQUIRED PATHS "${mpcomm_DIR}" NO_DEFAULT_PATH)
else()
    find_package(mpcomm REQUIRED)
endif()

# The wheel's exported target may carry a broken include directory like
# <site-packages>/include. Override it with the real helper-reported path.
if(TARGET mpcomm::mpcomm AND EXISTS "${MPCOMM_INCLUDE_DIR}")
    set_property(TARGET mpcomm::mpcomm PROPERTY
        INTERFACE_INCLUDE_DIRECTORIES "${MPCOMM_INCLUDE_DIR}"
    )
    message(STATUS "Using pip-installed MPComm package")
    message(STATUS "MPComm include dir: ${MPCOMM_INCLUDE_DIR}")
    if(MPCOMM_LIB_DIR)
        message(STATUS "MPComm lib dir: ${MPCOMM_LIB_DIR}")
    endif()
else()
    message(STATUS "Using CMake package MPComm target")
endif()

# Build the scatter test executable
add_executable(scatter_test scatter_test.cpp)

target_link_libraries(scatter_test PRIVATE
    ${_MPCOMM_LINK_TARGET}
    ${NUMA_LIBRARY}
)

if(MPCOMM_INCLUDE_DIR)
    target_include_directories(scatter_test PRIVATE "${MPCOMM_INCLUDE_DIR}")
endif()

# When linking against the pip-installed shared library, embed its directory in
# the runtime search path so ./build/scatter_test can run without extra exports.
if(MPCOMM_LIB_DIR)
    set_target_properties(scatter_test PROPERTIES
        BUILD_RPATH "${MPCOMM_LIB_DIR}"
    )
endif()

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
