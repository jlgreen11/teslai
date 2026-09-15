import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000", "/login": "http://localhost:8000" },
  },
  build: { outDir: "../teslai/api/web", emptyOutDir: true, chunkSizeWarningLimit: 1600 },
});
