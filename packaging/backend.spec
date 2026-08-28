# PyInstaller spec for the Snapir geometry backend.
# Produces a single folder the Electron installer ships as `resources/backend`.
#
#   cd app && npm run backend
#
# OCCT is large, so this is a one-folder build rather than one file: startup is
# far faster and the installer compresses it well.

import os
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

block_cipher = None
root = os.path.abspath(os.path.join(os.getcwd(), ".."))

a = Analysis(
    [os.path.join(root, "packaging", "server_entry.py")],
    pathex=[root],
    binaries=collect_dynamic_libs("OCP"),
    datas=[],
    hiddenimports=[
        "OCP", "snapir", "snapir.server", "snapir.solid", "snapir.parser",
        "snapir.tessellate", "snapir.designx", "snapir.planes", "snapir.store",
        *collect_submodules("uvicorn"),
        *collect_submodules("shapely"),
    ],
    hookspath=[], runtime_hooks=[], excludes=["tkinter", "matplotlib"],
    cipher=block_cipher, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="snapir-server",
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False,
               upx=False, name="backend")
