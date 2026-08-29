cmake_minimum_required(VERSION 3.22)
project(snapir_android CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The whole point of the C++ core: the same sources the desktop runs, compiled
# for the phone. Nothing here is Android-specific except the JNI entry point.
set(CORE ${SNAPIR_NATIVE_ROOT})

add_library(snapir SHARED
  ${CORE}/src/model.cpp
  ${CORE}/src/csv.cpp
  ${CORE}/src/geometry.cpp
  ${CORE}/src/planes.cpp
  ${CORE}/src/topology.cpp
  ${CORE}/src/parser.cpp
  ${CORE}/src/solid.cpp
  ${CORE}/src/tessellate.cpp
  ${CORE}/src/designx.cpp
  ${CORE}/src/store.cpp
  ${CORE}/src/service.cpp
  jni_bridge.cpp
)

target_include_directories(snapir PRIVATE
  ${CORE}/include
  ${CORE}
  ${OCCT_ANDROID_ROOT}/include/opencascade
  ${OCCT_ANDROID_ROOT}/inc
)

target_compile_definitions(snapir PRIVATE SNAPIR_WITH_OCCT=1)

# OCCT is cross-compiled static, so the app ships one .so rather than forty-odd.
# The link order matters for a static build: dependents before dependencies.
set(OCCT_LIBS
  TKDESTEP TKDEIGES TKDE TKXCAF TKVCAF TKCAF TKLCAF TKCDF
  TKOffset TKFillet TKBool TKBO TKPrim TKShHealing TKMesh
  TKTopAlgo TKGeomAlgo TKBRep TKGeomBase TKG3d TKG2d
  TKXSBase TKMath TKernel
)

foreach(tk ${OCCT_LIBS})
  find_library(OCCT_${tk} NAMES ${tk} PATHS
    ${OCCT_ANDROID_ROOT}/lib
    ${OCCT_ANDROID_ROOT}/lin64/clang/lib
    ${OCCT_ANDROID_ROOT}/and64/clang/lib
    NO_DEFAULT_PATH)
  if(NOT OCCT_${tk})
    message(FATAL_ERROR "Missing OCCT toolkit ${tk} under ${OCCT_ANDROID_ROOT}. "
                        "Build it first with tools/build_occt_android.py")
  endif()
  list(APPEND OCCT_RESOLVED ${OCCT_${tk}})
endforeach()

find_library(log-lib log)

target_link_libraries(snapir
  # Repeated so the static toolkits can resolve each other's symbols whichever
  # direction the dependency runs.
  -Wl,--start-group ${OCCT_RESOLVED} -Wl,--end-group
  ${log-lib}
)
