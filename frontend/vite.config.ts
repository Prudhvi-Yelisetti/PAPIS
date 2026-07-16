import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react()],

    server: {
      port:       1420,
      strictPort: true,
      proxy: {
        "/api": {
          target:       "http://127.0.0.1:8765",
          changeOrigin: true,
          secure:       false,
        },
        "/ws": {
          target:       "ws://127.0.0.1:8765",
          ws:           true,
          changeOrigin: true,
        },
        "/health": {
          target:       "http://127.0.0.1:8765",
          changeOrigin: true,
        },
        "/docs": {
          target:       "http://127.0.0.1:8765",
          changeOrigin: true,
        },
      },
    },

    clearScreen: false,
    envPrefix:   ["VITE_", "TAURI_"],

    build: {
      target:    command === "serve" ? "esnext" : ["chrome105", "safari13"],
      minify:    command !== "serve" ? "esbuild" : false,
      sourcemap: command === "serve",
      outDir:    "dist",
    },
  };
});