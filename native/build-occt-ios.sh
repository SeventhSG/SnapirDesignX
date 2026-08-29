#!/usr/bin/env bash
# Cross-compile Open CASCADE for iOS: once for the device, once for the
# simulator.
#
# The flag list is build-occt-android.bat's, unchanged. That is the whole
# reason this is one CMake run per SDK rather than a dependency hunt: with
# visualization and Draw off and every USE_* off, OCCT has no third-party
# dependency to cross-compile first.
#
# Static, so the app links one binary instead of shipping forty-odd frameworks
# that would each need signing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS="${ROOT}/.deps"
SRC="${DEPS}/occt-src"
OCCT_TAG="${OCCT_TAG:-V7_9_3}"

# 7.9.3 matches the version behind the cadquery-ocp wheel, so the C++ and the
# Python reference can still be compared number for number.
if [ ! -d "${SRC}" ]; then
  echo "==> cloning OCCT ${OCCT_TAG}"
  git clone --depth 1 --branch "${OCCT_TAG}" \
    https://github.com/Open-Cascade-SAS/OCCT.git "${SRC}"
fi

build_slice() {
  local sysroot="$1" out="$2"
  local build="${DEPS}/occt-${out}-build" prefix="${DEPS}/occt-${out}"

  if [ -f "${prefix}/lib/libTKernel.a" ]; then
    echo "==> ${out} already built, skipping"
    return
  fi

  echo "==> building OCCT for ${sysroot} -> ${prefix}"
  cmake -S "${SRC}" -B "${build}" -G Ninja \
    -DCMAKE_SYSTEM_NAME=iOS \
    -DCMAKE_OSX_SYSROOT="${sysroot}" \
    -DCMAKE_OSX_ARCHITECTURES=arm64 \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=15.0 \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_LIBRARY_TYPE=Static \
    -DINSTALL_DIR_LAYOUT=Unix \
    -DBUILD_MODULE_Visualization=OFF -DBUILD_MODULE_Draw=OFF -DBUILD_MODULE_DETools=OFF \
    -DBUILD_MODULE_ApplicationFramework=ON -DBUILD_MODULE_DataExchange=ON \
    -DBUILD_DOC_Overview=OFF \
    -DUSE_FREETYPE=OFF -DUSE_TK=OFF -DUSE_TCL=OFF -DUSE_RAPIDJSON=OFF -DUSE_VTK=OFF \
    -DUSE_FFMPEG=OFF -DUSE_FREEIMAGE=OFF -DUSE_TBB=OFF -DUSE_OPENGL=OFF -DUSE_GLES2=OFF \
    -DUSE_D3D=OFF -DUSE_DRACO=OFF -DUSE_OPENVR=OFF -DUSE_XLIB=OFF \
    -DCMAKE_INSTALL_PREFIX="${prefix}"

  cmake --build "${build}" --target install
  # The build tree is several times the size of the install and nothing needs
  # it again; on a cached CI runner it is the difference between fitting and
  # not.
  rm -rf "${build}"
}

# The simulator slice first: with no signing certificate it is the only build
# that will ever actually run, so a failure there is worth hitting early.
build_slice iphonesimulator iossim
build_slice iphoneos ios

echo "OCCT_IOS_OK"
