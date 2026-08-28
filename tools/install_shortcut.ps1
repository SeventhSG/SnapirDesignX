<#
  Puts a "Snapir Design X" shortcut on the desktop.

  It points straight at the Electron runtime in node_modules with the app
  folder as its argument, so the app starts from the built renderer without a
  terminal window and without npm in the way. The Python geometry backend is
  started by the app itself.

  Once the NSIS installer is built, that installer creates its own Start Menu
  and desktop entries and this script is no longer needed.

      powershell -ExecutionPolicy Bypass -File tools\install_shortcut.ps1
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$app = Join-Path $root "app"
$electron = Join-Path $app "node_modules\electron\dist\electron.exe"
$icon = Join-Path $app "buildResources\icon.ico"
$dist = Join-Path $app "dist\index.html"

if (-not (Test-Path $electron)) {
  throw "Electron not found at $electron. Run 'npm install' in the app folder first."
}
if (-not (Test-Path $dist)) {
  throw "Renderer not built. Run 'npm run build' in the app folder first."
}
if (-not (Test-Path $icon)) {
  throw "Icon not found at $icon. Run 'python tools/make_icon.py' first."
}

$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "Snapir Design X.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = $electron
$sc.Arguments = '"' + $app + '"'
$sc.WorkingDirectory = $app
$sc.IconLocation = "$icon,0"
$sc.Description = "Leica iCON room surveys to solid bodies"
$sc.WindowStyle = 1
$sc.Save()

Write-Output "Shortcut created: $link"
Write-Output "Target:           $electron"
Write-Output "Icon:             $icon"
