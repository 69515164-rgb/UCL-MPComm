cmake_minimum_required(VERSION 3.15)

# ---------------------------------------------------------------------------
# Read version from the VERSION file (single source of truth)
# ---------------------------------------------------------------------------
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" _version_lines)
foreach(_line IN LISTS _version_lines)
    if(_line MATCHES "^MPCOMM_VERSION=(.+)$")
        set(MPCOMM_VERSION_TAG "${CMAKE_MATCH_1}")
    elseif(_line MATCHES "^MPCOMM_SEMVER=(.+)$")
        set(MPCOMM_SEMVER "${CMAKE_MATCH_1}")
    endif()
endforeach()
if(NOT MPCOMM_SEMVER)
    message(FATAL_ERROR "Failed to parse MPCOMM_SEMVER from VERSION file")
endif()
message(STATUS "MPComm version: ${MPCOMM_VERSION_TAG} (${MPCOMM_SEMVER})")

project(mpcomm VERSION ${MPCOMM_SEMVER} LANGUAGES CXX)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find ibverbs
find_library(IBVERBS_LIBRARY ibverbs REQUIRED)
find_path(IBVERBS_INCLUDE_DIR infiniband/verbs.h REQUIRED)

# Find numa library (for NUMA topology detection and NUMA-aware allocation)
find_library(NUMA_LIBRARY numa REQUIRED)
find_path(NUMA_INCLUDE_DIR numa.h REQUIRED)

# Vendor-specific options for QP UDP source port modification
# USE_MLNX: NVIDIA/Mellanox NICs (mlx5dv_modify_qp_udp_sport)
# USE_BNXT: Broadcom NICs (bnxt_re_dv_modify_qp_udp_sport)
option(USE_MLNX "Enable NVIDIA/Mellanox specific features" OFF)
option(USE_BNXT "Enable Broadcom specific features" OFF)
option(USE_CUDA "Enable CUDA/GPU memory support (requires nvidia-peermem)" OFF)
# Optional: build the H2D/D2H TMA kernels (.cu). Enabled by default; requires
# a CUDA toolkit with nvcc (>=12.0) and only produces SASS for sm_90 (Hopper).
# Has no effect unless USE_CUDA is also ON. Turn OFF to avoid the CUDA language
# dependency entirely (e.g. on build hosts without nvcc).
option(USE_CUDA_KERNELS "Build H2D/D2H TMA gather/scatter CUDA kernels" ON)

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
    find_library(CUDART_LIBRARY cudart PATHS /usr/local/cuda/lib64 QUIET)
    if(NOT CUDA_DRIVER_LIBRARY)
        message(WARNING "CUDA driver library not found, USE_CUDA features may not work")
    endif()

    if(USE_CUDA_KERNELS)
        # Enable CUDA language only when building the .cu kernels
        enable_language(CUDA)
        set(CMAKE_CUDA_STANDARD 17)
        set(CMAKE_CUDA_STANDARD_REQUIRED ON)
        # The TMA kernels use Hopper-only PTX instructions (cp.async.bulk,
        # mbarrier.arrive.expect_tx, ...), which require sm_90+. We therefore
        # default CMAKE_CUDA_ARCHITECTURES to 90 here, and additionally pin the
        # .cu source file to sm_90 below so it is never compiled for older
        # architectures even if the user overrides CMAKE_CUDA_ARCHITECTURES.
        if(NOT CMAKE_CUDA_ARCHITECTURES)
            set(CMAKE_CUDA_ARCHITECTURES "90")
        endif()
        if(NOT CUDART_LIBRARY)
            message(WARNING "CUDA runtime library not found, TMA kernels may not link")
        endif()
    endif()
endif()

# Source files
set(MPCOMM_SOURCES src/mpcomm.cpp)

# Add PXN proxy sources
list(APPEND MPCOMM_SOURCES src/mpcomm_pxn.cpp)

# Add TMA kernel sources only when explicitly enabled
if(USE_CUDA AND USE_CUDA_KERNELS)
    list(APPEND MPCOMM_SOURCES src/mpcomm_tma_kernels.cu)
    # TMA instructions require Hopper; pin this file to sm_90 regardless of
    # the global CMAKE_CUDA_ARCHITECTURES so that ptxas does not try to emit
    # SASS for sm_75/80/86 (which would fail with "requires .target sm_90").
    set_source_files_properties(src/mpcomm_tma_kernels.cu
        PROPERTIES CUDA_ARCHITECTURES "90"
    )
endif()

# MPComm static library
add_library(mpcomm_static STATIC
    ${MPCOMM_SOURCES}
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
target_include_directories(mpcomm_static PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(mpcomm_static PUBLIC
    ${IBVERBS_LIBRARY}
    ${NUMA_LIBRARY}
    pthread
)

# MPComm shared library
add_library(mpcomm_shared SHARED
    ${MPCOMM_SOURCES}
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
target_include_directories(mpcomm_shared PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
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

    if(USE_CUDA_KERNELS)
        target_compile_definitions(mpcomm_static PUBLIC MPCOMM_ENABLE_CUDA_KERNELS)
        target_compile_definitions(mpcomm_shared PUBLIC MPCOMM_ENABLE_CUDA_KERNELS)
        if(CUDART_LIBRARY)
            target_link_libraries(mpcomm_static PUBLIC ${CUDART_LIBRARY})
            target_link_libraries(mpcomm_shared PRIVATE ${CUDART_LIBRARY})
        endif()
    endif()
endif()

# Enable position independent code for static library
# Required when linking into shared libraries (e.g., Python modules)
set_target_properties(mpcomm_static PROPERTIES POSITION_INDEPENDENT_CODE ON)

# Inject version string into C++ code via compile definition
target_compile_definitions(mpcomm_static PRIVATE MPCOMM_VERSION_STRING="${MPCOMM_VERSION_TAG}")
target_compile_definitions(mpcomm_shared PRIVATE MPCOMM_VERSION_STRING="${MPCOMM_VERSION_TAG}")

# Compiler flags
foreach(_target mpcomm_static mpcomm_shared)
    # CXX flags (GCC/Clang)
    target_compile_options(${_target} PRIVATE
        $<$<COMPILE_LANGUAGE:CXX>:-Wall -Wextra -Werror -O2>
    )
    # CUDA flags (nvcc) — use nvcc-native equivalents
    if(USE_CUDA AND USE_CUDA_KERNELS)
        target_compile_options(${_target} PRIVATE
            $<$<COMPILE_LANGUAGE:CUDA>:-Xcompiler=-Wall,-Wextra,-Werror -O2>
        )
    endif()
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

if(DEFINED SKBUILD)
    # -----------------------------------------------------------------
    # pip install / wheel build mode (scikit-build-core)
    # Pack everything into the "mpcomm" Python package directory so that
    # a single `pip install` provides both Python AND C++ interfaces.
    # -----------------------------------------------------------------
    set(_PKG_PREFIX mpcomm)

    # Python extension module + __init__.py
    if(BUILD_MPCOMM_PYTHON)
        install(TARGETS mpcomm_py
            LIBRARY DESTINATION ${_PKG_PREFIX}
        )
        install(FILES python/__init__.py
            DESTINATION ${_PKG_PREFIX}
        )
    endif()

    # Deploy scripts  ->  mpcomm/scripts/
    install(FILES deploy/check_install.sh
        DESTINATION ${_PKG_PREFIX}/scripts
        PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE
                    GROUP_READ GROUP_EXECUTE
                    WORLD_READ WORLD_EXECUTE
    )

    # C++ header files  ->  mpcomm/include/
    install(FILES include/mpcomm.h include/mpcomm_log.h
        DESTINATION ${_PKG_PREFIX}/include
    )

    # C++ static & shared libraries  ->  mpcomm/lib/
    install(TARGETS mpcomm_static mpcomm_shared
        EXPORT mpcommTargets
        ARCHIVE DESTINATION ${_PKG_PREFIX}/lib
        LIBRARY DESTINATION ${_PKG_PREFIX}/lib
    )

    # CMake package config  ->  mpcomm/lib/cmake/mpcomm/
    set(MPCOMM_CMAKE_INSTALL_DIR ${_PKG_PREFIX}/lib/cmake/mpcomm)

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

else()
    # -----------------------------------------------------------------
    # Standalone CMake build (the original behaviour)
    # -----------------------------------------------------------------

    # Install header files
    install(FILES include/mpcomm.h include/mpcomm_log.h
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

    # Install Python module
    if(BUILD_MPCOMM_PYTHON)
        install(TARGETS mpcomm_py
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}/python/mpcomm
        )
        install(FILES python/__init__.py
            DESTINATION ${CMAKE_INSTALL_LIBDIR}/python/mpcomm
        )
    endif()
endif()
