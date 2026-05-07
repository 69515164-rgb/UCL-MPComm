cmake_minimum_required(VERSION 3.14)
project(hello_mpcomm LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Locate an installed mpcomm package. Invoke cmake like:
#   cmake .. -DCMAKE_PREFIX_PATH=/opt/mpcomm
# or, when installed through the Python wheel:
#   cmake .. -Dmpcomm_DIR=$(python3 -c "import mpcomm; print(mpcomm.get_cmake_dir())")
find_package(mpcomm REQUIRED)

# Resolve include dir via Python to work around potential _IMPORT_PREFIX
# mismatches in pip-installed wheels (same trick as user_examples/CMakeLists.txt).
execute_process(
    COMMAND python3 -c "import mpcomm; print(mpcomm.get_include_dir())"
    OUTPUT_VARIABLE MPCOMM_INCLUDE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE _mpcomm_py_result
)
if(NOT _mpcomm_py_result EQUAL 0 OR NOT EXISTS "${MPCOMM_INCLUDE_DIR}")
    get_filename_component(_mpcomm_pkg_dir "${mpcomm_DIR}/../../.." ABSOLUTE)
    set(MPCOMM_INCLUDE_DIR "${_mpcomm_pkg_dir}/include")
endif()
message(STATUS "MPComm include dir: ${MPCOMM_INCLUDE_DIR}")

add_executable(hello_mpcomm hello_mpcomm.cpp)
target_include_directories(hello_mpcomm PRIVATE ${MPCOMM_INCLUDE_DIR})
target_link_libraries(hello_mpcomm PRIVATE mpcomm::mpcomm)
target_compile_options(hello_mpcomm PRIVATE -Wall -Wextra -O2)
