cmake_minimum_required(VERSION 3.15)
project(kpm_metrics_collector C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wall -Wextra -O2")

# FlexRIC paths
set(FLEXRIC_ROOT "/flexric")
set(FLEXRIC_BUILD "${FLEXRIC_ROOT}/build")
set(FLEXRIC_SRC "${FLEXRIC_ROOT}/src")

# Include directories
include_directories(
    ${FLEXRIC_SRC}
    ${FLEXRIC_SRC}/xApp
    ${FLEXRIC_SRC}/lib
    ${FLEXRIC_SRC}/util
    ${FLEXRIC_SRC}/sm
    ${FLEXRIC_BUILD}/src
)

# Link directories
link_directories(
    ${FLEXRIC_BUILD}/src/xApp
    ${FLEXRIC_BUILD}/src/lib
    /usr/local/lib/flexric
)

# Source files
set(SOURCES
    xapp_kpm_metrics_collector.c
)

# Executable
add_executable(xapp_kpm_metrics_collector ${SOURCES})

# Link libraries
target_link_libraries(xapp_kpm_metrics_collector
    e42_xapp_shared
    pthread
    sctp
)

# Install
install(TARGETS xapp_kpm_metrics_collector
    RUNTIME DESTINATION bin
)
