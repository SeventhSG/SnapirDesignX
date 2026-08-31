/**
 * Put the app's own name into the packaged executable.
 *
 * Electron ships its binary describing itself as "Electron" by GitHub, Inc.,
 * and that is what Task Manager, Alt-Tab and the file's Properties read --
 * the installer's shortcut name and the window title never touch it. So the
 * resources have to be rewritten after packaging.
 *
 * electron-builder does this itself, but only with `signAndEditExecutable`
 * left on, and turning it on also drags in its winCodeSign toolchain, whose
 * archive carries macOS symlinks that Windows refuses to extract without
 * Developer Mode. That is a signing dependency, and there is nothing here to
 * sign. So the same tool electron-builder would have used on Windows,
 * app-builder.exe, is called directly. It comes from app-builder-bin, which
 * is already a dependency, so this needs nothing that is not in the tree.
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

exports.default = async function stampExecutable(context) {
  if (context.electronPlatformName !== "win32") return;

  const { productName, version } = require("../package.json");
  const exe = path.join(context.appOutDir, `${productName}.exe`);
  if (!fs.existsSync(exe)) {
    throw new Error(`afterPack: no executable at ${exe}`);
  }

  // rcedit itself, vendored. Both electron-builder and its app-builder helper
  // reach for this through their winCodeSign download, which needs 7za on PATH
  // and extracts an archive full of macOS symlinks -- neither of which a
  // Windows build should have to care about. One 1.5 MB tool in the tree costs
  // less than that and builds the same on any machine.
  const tool = path.join(__dirname, "..", "buildResources", "rcedit-x64.exe");
  if (!fs.existsSync(tool)) {
    throw new Error(`afterPack: no rcedit at ${tool}`);
  }

  // Windows wants four parts in a file version.
  const args = [
    exe,
    "--set-version-string", "ProductName", productName,
    "--set-version-string", "FileDescription", productName,
    "--set-version-string", "CompanyName", "Snapir Design",
    "--set-version-string", "InternalName", productName,
    "--set-version-string", "OriginalFilename", `${productName}.exe`,
    "--set-file-version", `${version}.0`,
    "--set-product-version", `${version}.0`,
    "--set-icon", path.join(__dirname, "..", "buildResources", "icon.ico"),
  ];

  execFileSync(tool, args, { stdio: "inherit" });
  console.log(`  • stamped ${path.basename(exe)} as ${productName} ${version}`);
};
