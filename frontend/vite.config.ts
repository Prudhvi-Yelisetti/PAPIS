import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  plugins: [react()],

  // Vite serves on 1420 — must match tauri.conf.json devUrl
  server: {
    port:        1420,
    strictPort:  true,
    // Proxy API calls to the FastAPI backend during development
    // so you don't need to touch CORS when running `npm run dev` directly
    proxy: {
      "/api": {
        target:      "http://127.0.0.1:8765",
        changeOrigin: true,
      },
      "/ws": {
        target:  "ws://127.0.0.1:8765",
        ws:      true,
      },
    },
  },

  // During `tauri build`, prevent Vite from clearing the terminal output
  clearScreen: false,

  envPrefix: ["VITE_", "TAURI_"],

  build: {
    // Tauri supports modern targets — no need for legacy polyfills
    target:    command === "serve" ? "esnext" : ["chrome105", "safari13"],
    minify:    command !== "serve" ? "esbuild" : false,
    sourcemap: command === "serve",
  },
}));