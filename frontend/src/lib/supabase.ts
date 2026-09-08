import { createClient } from "@supabase/supabase-js";
import { demoEnabled } from "./personal-picks";

export function supabaseConfig(url: string | undefined, key: string | undefined) {
  if (!url?.trim() || !key?.trim()) return { error: "Supabase is not connected yet. Add VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY to frontend/.env.local, then restart the demo." };
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname))) throw Error();
    if (parsed.username || parsed.password || parsed.search || parsed.hash) throw Error();
    let publicKey = key.startsWith("sb_publishable_");
    if (!publicKey && key.split(".").length === 3) {
      const payload = JSON.parse(atob(key.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      publicKey = payload.role === "anon";
    }
    if (!publicKey) return { error: "Use only a Supabase publishable key (or legacy anon key). Secret/service-role keys must never be placed in frontend settings." };
    return { url: parsed.origin, key, error: "" };
  } catch { return { error: "Invalid Supabase project URL or publishable key. Check frontend/.env.local." }; }
}
const config = supabaseConfig(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY);
export const supabaseSetupError = config.error;
// UI release flag; Supabase settings and RLS independently enforce access.
export const publicSignupEnabled = import.meta.env.VITE_PUBLIC_SIGNUP === "true";
const offline = typeof window !== "undefined" && demoEnabled(import.meta.env.VITE_PERSONAL_DEMO, window.location.hostname);
// This client is browser-only. SSR/offline tests must never initialize a live
// account connection just because this checkout has .env.local configured.
export const supabase = typeof window !== "undefined" && !offline && config.url && config.key ? createClient(config.url, config.key, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  global: { fetch: (input, init) => fetch(input, { ...init, signal: init?.signal ?? AbortSignal.timeout(15000) }) },
}) : null;
