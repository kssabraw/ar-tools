import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // Surfaced early so a misconfigured deploy fails loudly rather than silently.
  console.warn("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set.");
}

// Auth only in M1. App data goes through the backend, never browser storage
// (CLAUDE.md frontend conventions).
export const supabase = createClient(url, anonKey);
