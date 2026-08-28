import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the built files load from file:// inside the packaged app.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true, target: "chrome128" },
});
