import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The review grid (AG Grid) is lazy-loaded, so it ends up in its own chunk automatically.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
