import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./ErrorBoundary";
import "./app.css";

/* The desktop window is frameless, so the titlebar has to keep a strip clear on
   the right for Electron's own window controls. Nothing else does, and holding
   that space on a phone costs room the interface needs. */
if (/Electron/i.test(navigator.userAgent)) {
  document.documentElement.dataset.shell = "electron";
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
);
