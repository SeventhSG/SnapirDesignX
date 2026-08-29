cmake_minimum_required(VERSION 3.24)
project(snapir_ios CXX OBJCXX)

# There is no .xcodeproj in this repository, and deliberately so: it is built
# on a CI runner by someone who cannot open Xcode, so the project has to be a
# text file that survives review in a diff. CMake generates the real one.
#
# Configured once per SDK rather than once for both. Xcode can express a
# per-SDK library path with [sdk=iphoneos*] conditionals, but OCCT lands in a
# different prefix for each slice and getting that wrong fails at link time on
# a machine nobody can attach a debugger to. Two configures, no conditionals.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_OBJCXX_STANDARD 17)

set(SNAPIR_NATIVE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../native" CACHE PATH
    "The C++ core")
set(OCCT_IOS_ROOT "" CACHE PATH "Open CASCADE install for this SDK")

if(NOT EXISTS "${OCCT_IOS_ROOT}/lib/libTKernel.a")
  message(FATAL_ERROR
    "No Open CASCADE at OCCT_IOS_ROOT=${OCCT_IOS_ROOT}. "
    "Build it first with native/build-occt-ios.sh")
endif()

set(CORE ${SNAPIR_NATIVE_ROOT})

# The same translation units the desktop and the phone compile. The only file
# here that is not shared is the shell itself.
set(SNAPIR_SOURCES
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
)

set(SHELL_SOURCES
  Sources/main.mm
  Sources/AppDelegate.mm
  Sources/SnapirViewController.mm
  Sources/NativeService.mm
  Sources/FolderImport.mm
  Sources/WebBridge.mm
)

# The built interface, staged out of app/dist by tools/build_ios.py. It goes
# into the bundle with its directory structure intact, because the service
# serves it off disk exactly as the Electron shell and the APK do.
set(WEB_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/Resources/web")
file(GLOB_RECURSE WEB_FILES "${WEB_ROOT}/*")
if(NOT WEB_FILES)
  message(FATAL_ERROR
    "No interface at ${WEB_ROOT}. Run tools/build_ios.py, which builds "
    "app/dist and stages it here.")
endif()

foreach(f ${WEB_FILES})
  file(RELATIVE_PATH rel "${WEB_ROOT}" "${f}")
  get_filename_component(dir "${rel}" DIRECTORY)
  # A trailing slash on the package location puts the file one directory too
  # deep, so the root case is spelled out rather than interpolated.
  if(dir STREQUAL "")
    set(where "Resources/web")
  else()
    set(where "Resources/web/${dir}")
  endif()
  # No HEADER_FILE_ONLY here: it would take these out of the copy phase, which
  # is the only reason they are listed as sources at all.
  set_source_files_properties(${f} PROPERTIES MACOSX_PACKAGE_LOCATION "${where}")
endforeach()

set(ASSET_CATALOG "${CMAKE_CURRENT_SOURCE_DIR}/Resources/Assets.xcassets")
if(EXISTS "${ASSET_CATALOG}")
  set_source_files_properties(${ASSET_CATALOG} PROPERTIES
    MACOSX_PACKAGE_LOCATION "Resources")
  list(APPEND WEB_FILES ${ASSET_CATALOG})
endif()

add_executable(Snapir MACOSX_BUNDLE
  ${SNAPIR_SOURCES}
  ${SHELL_SOURCES}
  ${WEB_FILES}
)

target_include_directories(Snapir PRIVATE
  ${CORE}/include
  ${CORE}
  ${OCCT_IOS_ROOT}/include/opencascade
  ${OCCT_IOS_ROOT}/inc
)

target_compile_definitions(Snapir PRIVATE SNAPIR_WITH_OCCT=1)
target_compile_options(Snapir PRIVATE -fexceptions -frtti)

# Dependents before dependencies, the same order the Android build uses.
#
# Note what is NOT here: -Wl,--start-group. Apple's ld64 does not implement the
# GNU group flags and errors on them, and it does not need them either -- it
# resolves circular references between static archives on its own. Copying the
# Android link line across verbatim fails here.
set(OCCT_LIBS
  TKDESTEP TKDEIGES TKDESTL TKDE TKXCAF TKVCAF TKCAF TKLCAF TKCDF
  TKOffset TKFillet TKBool TKBO TKPrim TKShHealing TKMesh
  TKTopAlgo TKGeomAlgo TKBRep TKGeomBase TKG3d TKG2d
  TKXSBase TKMath TKernel
)

foreach(tk ${OCCT_LIBS})
  set(archive ${OCCT_IOS_ROOT}/lib/lib${tk}.a)
  if(NOT EXISTS ${archive})
    message(FATAL_ERROR "Missing OCCT toolkit ${tk} at ${archive}")
  endif()
  list(APPEND OCCT_RESOLVED ${archive})
endforeach()

target_link_libraries(Snapir PRIVATE
  ${OCCT_RESOLVED}
  "-framework UIKit"
  "-framework WebKit"
  "-framework Foundation"
  "-framework UniformTypeIdentifiers"
  # CGRectZero, CGRectGetMidX and CGRectGetMaxY live here, not in UIKit.
  # UIKit's umbrella header declares them, so the code compiles either way;
  # they only come up missing at link, where -dead_strip means nothing pulls
  # CoreGraphics in on UIKit's behalf.
  "-framework CoreGraphics"
)

set_target_properties(Snapir PROPERTIES
  MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
  MACOSX_BUNDLE_BUNDLE_NAME "Snapir"
  MACOSX_BUNDLE_GUI_IDENTIFIER "com.snapirdesign.designx"
  MACOSX_BUNDLE_BUNDLE_VERSION "1.2.1"
  MACOSX_BUNDLE_SHORT_VERSION_STRING "1.2.1"

  # iPad first: this is a survey tool, not a phone tool. 1,2 is iPhone+iPad,
  # and all four orientations rather than the phone build's portrait lock.
  XCODE_ATTRIBUTE_TARGETED_DEVICE_FAMILY "1,2"
  XCODE_ATTRIBUTE_IPHONEOS_DEPLOYMENT_TARGET "15.0"
  XCODE_ATTRIBUTE_ASSETCATALOG_COMPILER_APPICON_NAME "AppIcon"
  XCODE_ATTRIBUTE_CLANG_ENABLE_OBJC_ARC "YES"

  # No Apple Developer account, so nothing is signed. The simulator does not
  # care, and the device build exists only to prove it compiles and links.
  XCODE_ATTRIBUTE_CODE_SIGNING_ALLOWED "NO"
  XCODE_ATTRIBUTE_CODE_SIGNING_REQUIRED "NO"
  XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY ""
)
