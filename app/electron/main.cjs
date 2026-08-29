/**
 * Electron main process.
 *
 * Starts the Python geometry backend as a private child process on loopback
 * and opens the window. The user never sees a port, a URL, or a terminal.
 */
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const DEV = process.env.SNAPIR_DEV === "1";

// Windows groups taskbar entries by this id, and uses it to find the icon.
if (process.platform === "win32") app.setAppUserModelId("com.snapirdesign.designx");
const PORT = 8765;
const HOST = "127.0.0.1";

let backend = null;
let win = null;
let quitting = false;
let adopted = false;      // an instance was already serving; we did not spawn

/** Resolve how to run the backend: bundled exe when packaged, module in dev. */
function backendCommand() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", "snapir-server.exe");
    return { cmd: exe, args: [], cwd: path.dirname(exe) };
  }
  // In development, prefer the native backend if it has been built, so dev runs
  // the same engine the installer ships. Fall back to the Python reference
  // implementation when it has not.
  const root = path.join(__dirname, "..", "..");
  const native = path.join(root, "native", "build", "snapir-server.exe");
  if (fs.existsSync(native)) {
    return { cmd: native, args: [], cwd: path.dirname(native) };
  }
  return {
    cmd: process.platform === "win32" ? "python" : "python3",
    args: ["-m", "snapir.server"],
    cwd: root,
  };
}

/** Is something already answering as a Snapir backend on our port? */
function probe(timeoutMs = 900) {
  return new Promise((resolve) => {
    const sock = net.connect(PORT, HOST);
    const done = (v) => { sock.destroy(); resolve(v); };
    sock.setTimeout(timeoutMs);
    sock.once("connect", () => done(true));
    sock.once("timeout", () => done(false));
    sock.once("error", () => done(false));
  });
}

/** Ask whatever holds the port to stand down, then wait for it to let go. */
async function evict() {
  try {
    await fetch(`http://${HOST}:${PORT}/shutdown`, { method: "POST" });
  } catch { /* not ours, or already gone */ }
  for (let i = 0; i < 24; i++) {
    if (!(await probe(300))) return true;
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

async function startBackend() {
  // We only get here holding the single-instance lock, so no sibling app is
  // running and anything on the port is left over from a previous session.
  // Adopting it would pin the app to stale code, so it is asked to exit.
  if (await probe()) {
    const freed = await evict();
    if (!freed) {
      adopted = true;      // something else owns the port; leave it alone
      return;
    }
  }
  const { cmd, args, cwd } = backendCommand();
  backend = spawn(cmd, args, {
    cwd,
    env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    windowsHide: true,
  });
  backend.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  backend.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  backend.on("error", (err) => {
    backend = null;
    if (quitting) return;
    dialog.showErrorBox(
      "Geometry engine could not start",
      err.code === "ENOENT"
        ? `Python was not found. Snapir needs Python 3.11 or newer on PATH.

Tried: ${cmd}`
        : String(err.message || err)
    );
  });

  backend.on("exit", (code) => {
    backend = null;
    // A clean shutdown, or one we asked for, is not an error.
    if (quitting || code === 0 || code === null) return;
    if (win && !win.isDestroyed()) {
      dialog.showErrorBox(
        "Geometry engine stopped",
        `The Snapir backend exited with code ${code}. Restart the app to continue.`
      );
    }
  });
}

/** Wait until the backend is accepting connections, or give up and say so. */
function waitForBackend(timeoutMs = 40000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(PORT, HOST);
      sock.once("connect", () => { sock.destroy(); resolve(); });
      sock.once("error", () => {
        sock.destroy();
        if (Date.now() - started > timeoutMs) {
          reject(new Error("The geometry engine did not start in time."));
        } else {
          setTimeout(attempt, 250);
        }
      });
    };
    attempt();
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    show: false,
    backgroundColor: "#F6F6F3",
    icon: path.join(__dirname, "..", "buildResources", "icon.ico"),
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#FBFBF9", symbolColor: "#5A5A61", height: 40 },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  const reveal = () => {
    if (!win || win.isDestroyed() || win.isVisible()) return;
    win.show();
    win.focus();
  };
  win.once("ready-to-show", reveal);
  // If the renderer never reports ready, show the window anyway. An invisible
  // process still holds the single-instance lock, so the app would look dead
  // and clicking the shortcut would do nothing at all.
  setTimeout(reveal, 2500);

  win.webContents.on("did-fail-load", (_e, code, desc, url) => {
    reveal();
    dialog.showErrorBox("Snapir could not load",
      `The interface failed to load.

${desc} (${code})
${url}`);
  });
  win.webContents.on("render-process-gone", (_e, details) => {
    dialog.showErrorBox("Snapir stopped responding",
      `The interface process ended: ${details.reason}`);
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (DEV) {
    win.loadURL("http://localhost:5173");
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

ipcMain.handle("pick-folder", async () => {
  const r = await dialog.showOpenDialog(win, {
    title: "Choose a survey folder",
    properties: ["openDirectory"],
  });
  return r.canceled ? null : r.filePaths[0];
});

// The Windows caption buttons live outside the page, so the theme has to be
// pushed to them separately or they stay light on a dark window.
ipcMain.handle("set-theme", async (_e, dark) => {
  if (!win || win.isDestroyed()) return;
  win.setBackgroundColor(dark ? "#141416" : "#F6F6F3");
  try {
    win.setTitleBarOverlay({
      color: dark ? "#181819" : "#FBFBF9",
      symbolColor: dark ? "#A6A5A0" : "#5A5A61",
      height: 40,
    });
  } catch { /* not supported on this platform */ }
});

ipcMain.handle("reveal", async (_e, target) => {
  if (target) shell.showItemInFolder(target);
});

ipcMain.handle("backend-ready", async () => {
  try {
    await waitForBackend();
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e.message || e) };
  }
});

// One window per machine. A second launch focuses the first instead of
// starting a rival app and a rival backend.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!win || win.isDestroyed()) { createWindow(); return; }
    if (win.isMinimized()) win.restore();
    if (!win.isVisible()) win.show();
    win.focus();
  });

  app.whenReady().then(async () => {
    createWindow();
    await startBackend();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}

function stopBackend() {
  quitting = true;
  if (!backend || adopted) return;    // never kill a backend we did not start
  backend.kill();
  backend = null;
}

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", stopBackend);
process.on("exit", stopBackend);
