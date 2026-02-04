cmake_minimum_required(VERSION 3.10)
project(mpcomm LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find ibverbs
find_library(IBVERBS_LIBRARY ibverbs REQUIRED)
find_path(IBVERBS_INCLUDE_DIR infiniband/verbs.h REQUIRED)

# Find numa library (for NUMA topology detection)
find_library(NUMA_LIBRARY numa REQUIRED)
find_path(NUMA_INCLUDE_DIR numaif.h REQUIRED)

# Vendor-specific options for QP UDP source port modification
# USE_MLNX: NVIDIA/Mellanox NICs (mlx5dv_modify_qp_udp_sport)
# USE_BNXT: Broadcom NICs (bnxt_re_dv_modify_qp_udp_sport)
option(USE_MLNX "Enable NVIDIA/Mellanox specific features" OFF)
option(USE_BNXT "Enable Broadcom specific features" OFF)

# Find vendor-specific libraries
if(USE_MLNX)
    find_library(MLX5_LIBRARY mlx5 QUIET)
    if(NOT MLX5_LIBRARY)
        message(WARNING "mlx5 library not found, USE_MLNX features may not work")
    endif()
endif()

if(USE_BNXT)
    find_library(BNXT_RE_LIBRARY bnxt_re QUIET)
    if(NOT BNXT_RE_LIBRARY)
        message(WARNING "bnxt_re library not found, USE_BNXT features may not work")
    endif()
endif()

# MPComm library
add_library(mpcomm STATIC
    src/mpcomm.cpp
)

target_include_directories(mpcomm PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${IBVERBS_INCLUDE_DIR}
)

target_link_libraries(mpcomm PUBLIC
    ${IBVERBS_LIBRARY}
    ${NUMA_LIBRARY}
    pthread
)

# Add vendor-specific compile definitions and libraries
if(USE_MLNX)
    target_compile_definitions(mpcomm PUBLIC USE_MLNX)
    if(MLX5_LIBRARY)
        target_link_libraries(mpcomm PUBLIC ${MLX5_LIBRARY})
    endif()
endif()

if(USE_BNXT)
    target_compile_definitions(mpcomm PUBLIC USE_BNXT)
    if(BNXT_RE_LIBRARY)
        target_link_libraries(mpcomm PUBLIC ${BNXT_RE_LIBRARY})
    endif()
endif()

# Enable position independent code for static library
# Required when linking into shared libraries (e.g., Python modules)
set_target_properties(mpcomm PROPERTIES POSITION_INDEPENDENT_CODE ON)

# Compiler flags
target_compile_options(mpcomm PRIVATE
    -Wall
    -Wextra
    -Werror
    -O2
)

# Python bindings (optional)
option(BUILD_MPCOMM_PYTHON "Build MPComm Python bindings" OFF)
if(BUILD_MPCOMM_PYTHON)
    # First find Python
    find_package(Python3 COMPONENTS Interpreter Development REQUIRED)

    # Try to find pybind11 via CMake config, fallback to Python module
    find_package(pybind11 QUIET CONFIG)
    if(NOT pybind11_FOUND)
        # Get pybind11 CMake directory from Python
        execute_process(
            COMMAND ${Python3_EXECUTABLE} -m pybind11 --cmakedir
            OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
            OUTPUT_STRIP_TRAILING_WHITESPACE
            RESULT_VARIABLE PYBIND11_CMAKE_RESULT
        )
        if(PYBIND11_CMAKE_RESULT EQUAL 0 AND EXISTS "${PYBIND11_CMAKE_DIR}")
            set(pybind11_DIR "${PYBIND11_CMAKE_DIR}")
            find_package(pybind11 REQUIRED CONFIG)
        else()
            message(FATAL_ERROR "pybind11 not found. Please install it: pip install pybind11")
        endif()
    endif()

    pybind11_add_module(mpcomm_py python/mpcomm_py.cpp)
    
    set_target_properties(mpcomm_py PROPERTIES
        OUTPUT_NAME "mpcomm"
        INSTALL_RPATH "$ORIGIN"
    )

    target_include_directories(mpcomm_py PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${IBVERBS_INCLUDE_DIR}
        ${Python3_INCLUDE_DIRS}
    )

    target_link_libraries(mpcomm_py PRIVATE
        mpcomm
        ${Python3_LIBRARIES}
    )

    # Get Python site-packages path
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -c "import site; print(site.getsitepackages()[0])"
        OUTPUT_VARIABLE PYTHON_SITE_PACKAGES
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )

    # Install Python module
    install(TARGETS mpcomm_py
        LIBRARY DESTINATION ${PYTHON_SITE_PACKAGES}
    )
endif()

# Example executable (optional)
option(BUILD_MPCOMM_EXAMPLES "Build MPComm examples" OFF)
if(BUILD_MPCOMM_EXAMPLES)
    add_executable(mpcomm_example
        examples/basic_example.cpp
    )
    target_link_libraries(mpcomm_example mpcomm)
endif()

# Test executable (optional)
option(BUILD_MPCOMM_TESTS "Build MPComm tests" OFF)
if(BUILD_MPCOMM_TESTS)
    add_executable(mpcomm_test
        tests/mpcomm_test.cpp
    )
    target_link_libraries(mpcomm_test mpcomm)
endif()
