import preact from "@preact/preset-vite";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

function fromConfig(relativePath: string): string {
  return fileURLToPath(new URL(relativePath, import.meta.url));
}

export default defineConfig({
  base: "/player/",
  plugins: [preact()],
  resolve: {
    alias: {
      "@": fromConfig("src/"),
    },
  },
  build: {
    outDir: fromConfig("../custom_plugins/local_voice/player"),
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
  server: {
    strictPort: false,
  },
});
