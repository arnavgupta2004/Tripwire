import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Override with TRIPWIRE_API=http://127.0.0.1:8100 if port 8000 is taken.
      "/api": { target: process.env.TRIPWIRE_API || "http://127.0.0.1:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, ""),
                ws: true },
    },
  },
});
