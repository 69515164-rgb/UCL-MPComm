cmake_minimum_required(VERSION 3.14)
project(mpcomm VERSION 1.0.0 LANGUAGES CXX)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

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
option(USE_CUDA "Enable CUDA/GPU memory support (requires nvidia-peermem)" OFF)

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

if(USE_CUDA)
    find_library(CUDA_DRIVER_LIBRARY cuda PATHS /usr/local/cuda/lib64 /usr/lib/x86_64-linux-gnu QUIET)
    find_path(CUDA_INCLUDE_DIR cuda.h PATHS /usr/local/cuda/include QUIET)
    if(NOT CUDA_DRIVER_LIBRARY)
        message(WARNING "CUDA driver library not found, USE_CUDA features may not work")
    endif()
endif()

# MPComm static library
add_library(mpcomm_static STATIC
    src/mpcomm.cpp
)
set_target_properties(mpcomm_static PROPERTIES
    OUTPUT_NAME mpcomm
    EXPORT_NAME mpcomm_static
)

target_include_directories(mpcomm_static PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    ${IBVERBS_INCLUDE_DIR}
)

target_link_libraries(mpcomm_static PUBLIC
    ${IBVERBS_LIBRARY}
    ${NUMA_LIBRARY}
    pthread
)

# MPComm shared library
add_library(mpcomm_shared SHARED
    src/mpcomm.cpp
)
set_target_properties(mpcomm_shared PROPERTIES
    OUTPUT_NAME mpcomm
    EXPORT_NAME mpcomm
    VERSION ${PROJECT_VERSION}
    SOVERSION ${PROJECT_VERSION_MAJOR}
)

target_include_directories(mpcomm_shared PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    ${IBVERBS_INCLUDE_DIR}
)

target_link_libraries(mpcomm_shared PRIVATE
    ${IBVERBS_LIBRARY}
    ${NUMA_LIBRARY}
    pthread
)

# Convenience alias (points to shared library by default)
add_library(mpcomm ALIAS mpcomm_shared)

# Add vendor-specific compile definitions and libraries
if(USE_MLNX)
    target_compile_definitions(mpcomm_static PUBLIC USE_MLNX)
    target_compile_definitions(mpcomm_shared PUBLIC USE_MLNX)
    if(MLX5_LIBRARY)
        target_link_libraries(mpcomm_static PUBLIC ${MLX5_LIBRARY})
        target_link_libraries(mpcomm_shared PRIVATE ${MLX5_LIBRARY})
    endif()
endif()

if(USE_BNXT)
    target_compile_definitions(mpcomm_static PUBLIC USE_BNXT)
    target_compile_definitions(mpcomm_shared PUBLIC USE_BNXT)
    if(BNXT_RE_LIBRARY)
        target_link_libraries(mpcomm_static PUBLIC ${BNXT_RE_LIBRARY})
        target_link_libraries(mpcomm_shared PRIVATE ${BNXT_RE_LIBRARY})
    endif()
endif()

if(USE_CUDA)
    target_compile_definitions(mpcomm_static PUBLIC USE_CUDA)
    target_compile_definitions(mpcomm_shared PUBLIC USE_CUDA)
    if(CUDA_INCLUDE_DIR)
        target_include_directories(mpcomm_static PUBLIC ${CUDA_INCLUDE_DIR})
        target_include_directories(mpcomm_shared PUBLIC ${CUDA_INCLUDE_DIR})
    endif()
    if(CUDA_DRIVER_LIBRARY)
        target_link_libraries(mpcomm_static PUBLIC ${CUDA_DRIVER_LIBRARY})
        target_link_libraries(mpcomm_shared PRIVATE ${CUDA_DRIVER_LIBRARY})
    endif()
endif()

# Enable position independent code for static library
# Required when linking into shared libraries (e.g., Python modules)
set_target_properties(mpcomm_static PROPERTIES POSITION_INDEPENDENT_CODE ON)

# Compiler flags
foreach(_target mpcomm_static mpcomm_shared)
    target_compile_options(${_target} PRIVATE
        -Wall
        -Wextra
        -Werror
        -O2
    )
endforeach()

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
        mpcomm_static
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
    target_link_libraries(mpcomm_example mpcomm_shared)
endif()

# =====================================================================
# Install rules
# =====================================================================

# Install header files
install(FILES include/mpcomm.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

# Install libraries
install(TARGETS mpcomm_static mpcomm_shared
    EXPORT mpcommTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

# Install CMake package config files
set(MPCOMM_CMAKE_INSTALL_DIR ${CMAKE_INSTALL_LIBDIR}/cmake/mpcomm)

install(EXPORT mpcommTargets
    FILE mpcommTargets.cmake
    NAMESPACE mpcomm::
    DESTINATION ${MPCOMM_CMAKE_INSTALL_DIR}
)

configure_package_config_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/mpcommConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/mpcommConfig.cmake
    INSTALL_DESTINATION ${MPCOMM_CMAKE_INSTALL_DIR}
)

write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/mpcommConfigVersion.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)

install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/mpcommConfig.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/mpcommConfigVersion.cmake
    DESTINATION ${MPCOMM_CMAKE_INSTALL_DIR}
)

# Install Python module (when built)
if(BUILD_MPCOMM_PYTHON)
    install(TARGETS mpcomm_py
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}/python/mpcomm
    )
    install(FILES python/__init__.py
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/python/mpcomm
    )
endif()
