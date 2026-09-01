/** The only bridge between the page and the machine. Nothing else is exposed. */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("snapir", {
  pickFolder: () => ipcRenderer.invoke("pick-folder"),
  pickSdxp: () => ipcRenderer.invoke("pick-sdxp"),
  reveal: (p) => ipcRenderer.invoke("reveal", p),
  setTheme: (dark) => ipcRenderer.invoke("set-theme", dark),
  backendReady: () => ipcRenderer.invoke("backend-ready"),
  api: "http://127.0.0.1:8765",
});
