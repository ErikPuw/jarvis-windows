import { defineConfig } from "vite";
import { readFileSync } from "fs";
import path from "path";

export default defineConfig(() => {
  const rootDir = typeof import.meta.dirname !== "undefined" ? path.resolve(import.meta.dirname, "..") : process.cwd();
  // Single version source (CHANGELOG.md "Quy tắc đánh số"): the repo-root VERSION file.
  const appVersion = readFileSync(path.join(rootDir, "VERSION"), "utf-8").trim();
  return {
    define: {
      __APP_VERSION__: JSON.stringify(appVersion),
    },
    server: {
      host: true,
      port: 5173,
      allowedHosts: true,
      proxy: {
        "/ws": {
          target: "https://127.0.0.1:8340",
          ws: true,
          secure: false,
          changeOrigin: true,
        },
        "/api": {
          target: "https://127.0.0.1:8340",
          secure: false,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "three",
              test: /node_modules[\\/]three[\\/]/,
            },
          ],
        },
      },
    },
  },
  };
});
