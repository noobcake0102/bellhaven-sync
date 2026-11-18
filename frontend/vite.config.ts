import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// Builds into ../static/dist, which Flask serves. `npm run build` after any UI change.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/dist/",
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    outDir: "../static/dist", emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: "app.js", chunkFileNames: "[name].js", assetFileNames: "[name].[ext]" } },
  },
  server: { proxy: { "/api": "http://127.0.0.1:5000" } },
});
