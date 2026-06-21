/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Local dev convenience: proxy API calls to the backend so the SPA runs same-origin.
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    css: true,
  },
});
