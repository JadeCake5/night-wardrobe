import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const rootDir = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(rootDir, "src") },
  },
  build: {
    outDir: "../../static/copilot",
    emptyOutDir: true,
    lib: {
      entry: "src/main.tsx",
      name: "WorkshopCopilotIsland",
      formats: ["iife"],
      fileName: () => "copilot.js",
    },
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        assetFileNames: (info) => {
          const name = info.names?.[0] || info.name || "";
          return name.endsWith(".css") ? "copilot.css" : "assets/[name][extname]";
        },
      },
    },
  },
});
