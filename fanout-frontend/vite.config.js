import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Served as a section of the AR Tools suite under /fanout (the AR Tools Netlify
// build assembles this app's output into dist/fanout). The base path must match
// the router basename in src/App.tsx and the /fanout/* Netlify redirect.
export default defineConfig({
    base: "/fanout/",
    plugins: [react()],
});
