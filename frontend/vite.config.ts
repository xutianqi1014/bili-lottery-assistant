import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        ws: true,
      },
    }
  },
  build: {
    outDir: resolve(__dirname, "../web_static/dist"),
    emptyOutDir: true,
    sourcemap: false
  }
});
