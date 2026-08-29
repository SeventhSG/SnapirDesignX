@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set PATH=C:\Users\gamin\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\local-packages\Python311\site-packages\ninja\data\bin;%PATH%
set N=C:\Users\gamin\Downloads\Snapir-Design-X\native
set D=C:\Users\gamin\Downloads\Snapir-Design-X\.deps\occt
cmake -S %N% -B %N%\build -G Ninja -DCMAKE_BUILD_TYPE=Release -DOpenCASCADE_DIR=%D%\cmake || exit /b 1
cmake --build %N%\build || exit /b 1
echo FULL_OK
