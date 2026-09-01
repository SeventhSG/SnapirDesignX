@echo off
REM Cross-compile Open CASCADE for arm64-v8a.
REM
REM Same module selection as the desktop build, which is the point: with
REM visualization and Draw off there are no third-party dependencies to
REM cross-compile first, so this is one CMake run rather than a dependency hunt.
REM Static, so the app ships one .so instead of forty-odd.

set D=C:\Users\gamin\Downloads\Snapir-Design-X\.deps
set A=%D%\android
set NDK=%A%\sdk\ndk\27.0.12077973
set PATH=%A%\sdk\cmake\3.22.1\bin;%PATH%

if not exist "%NDK%" (
  echo No NDK at %NDK%
  exit /b 1
)

cmake -S %D%\occt-src -B %D%\occt-android-build -G Ninja ^
 -DCMAKE_TOOLCHAIN_FILE=%NDK%\build\cmake\android.toolchain.cmake ^
 -DANDROID_ABI=arm64-v8a ^
 -DANDROID_PLATFORM=android-26 ^
 -DANDROID_STL=c++_shared ^
 -DCMAKE_BUILD_TYPE=Release ^
 -DBUILD_LIBRARY_TYPE=Static ^
 -DINSTALL_DIR_LAYOUT=Unix ^
 -DBUILD_MODULE_Visualization=OFF -DBUILD_MODULE_Draw=OFF -DBUILD_MODULE_DETools=OFF ^
 -DBUILD_MODULE_ApplicationFramework=ON -DBUILD_MODULE_DataExchange=ON ^
 -DBUILD_DOC_Overview=OFF ^
 -DUSE_FREETYPE=OFF -DUSE_TK=OFF -DUSE_TCL=OFF -DUSE_RAPIDJSON=ON -DUSE_VTK=OFF ^
 -D3RDPARTY_RAPIDJSON_INCLUDE_DIR=%D%\rapidjson\include ^
 -DUSE_FFMPEG=OFF -DUSE_FREEIMAGE=OFF -DUSE_TBB=OFF -DUSE_OPENGL=OFF -DUSE_GLES2=OFF ^
 -DUSE_D3D=OFF -DUSE_DRACO=OFF -DUSE_OPENVR=OFF -DUSE_XLIB=OFF ^
 -DCMAKE_INSTALL_PREFIX=%D%\occt-android || exit /b 1

cmake --build %D%\occt-android-build --target install || exit /b 1
echo OCCT_ANDROID_OK
