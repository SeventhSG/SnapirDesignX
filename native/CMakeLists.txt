cmake_minimum_required(VERSION 3.20)
project(snapir_core CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
  add_compile_options(/W4 /permissive- /utf-8 /EHsc)
  # The survey CSVs are UTF-8; do not let MSVC guess the source encoding.
  add_compile_options(/wd4100)
else()
  add_compile_options(-Wall -Wextra)
endif()

# The geometry kernel is only needed for solids, tessellation and STEP/IGES.
# Everything up to and including the classifier builds and is verifiable
# without it, which is what lets the port be checked in two halves.
option(SNAPIR_WITH_OCCT "Build the parts that need Open CASCADE" ON)

set(CORE_SOURCES
  src/model.cpp
  src/csv.cpp
  src/geometry.cpp
  src/planes.cpp
  src/topology.cpp
  src/parser.cpp
)

if(SNAPIR_WITH_OCCT)
  list(APPEND CORE_SOURCES
    src/solid.cpp
    src/tessellate.cpp
    src/designx.cpp
    src/store.cpp
  )
endif()

add_library(snapir_core STATIC ${CORE_SOURCES})
target_include_directories(snapir_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(SNAPIR_WITH_OCCT)
  find_package(OpenCASCADE REQUIRED)
  target_include_directories(snapir_core PUBLIC ${OpenCASCADE_INCLUDE_DIR})
  target_link_libraries(snapir_core PUBLIC
    TKernel TKMath TKG2d TKG3d TKGeomBase TKBRep
    TKGeomAlgo TKTopAlgo TKPrim TKBO TKBool TKOffset TKShHealing TKMesh
    TKDESTEP TKDEIGES TKDESTL TKXSBase
  )
  target_compile_definitions(snapir_core PUBLIC SNAPIR_WITH_OCCT=1)
endif()

add_executable(dump_parse tools/dump_parse.cpp)
target_link_libraries(dump_parse PRIVATE snapir_core)

if(SNAPIR_WITH_OCCT)
  add_executable(dump_solid tools/dump_solid.cpp)
  target_link_libraries(dump_solid PRIVATE snapir_core)

  add_executable(check_openings tools/check_openings.cpp)
  target_link_libraries(check_openings PRIVATE snapir_core)

  add_executable(check_export tools/check_export.cpp)
  target_link_libraries(check_export PRIVATE snapir_core)

  # The sidecar the desktop app spawns. Same name and location the packaged
  # Electron shell already looks for, so main.cjs is unchanged.
  add_executable(snapir-server src/main.cpp src/service.cpp)
  target_link_libraries(snapir-server PRIVATE snapir_core)
  if(WIN32)
    target_link_libraries(snapir-server PRIVATE ws2_32 crypt32)
  else()
    find_package(Threads REQUIRED)
    target_link_libraries(snapir-server PRIVATE Threads::Threads)
  endif()
endif()
