import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const NLP_SERVICE_URL = Deno.env.get("NLP_SERVICE_URL") ?? "";
const NLP_API_KEY = Deno.env.get("NLP_API_KEY") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

// Internal tool: no billing, no credits, no caps. We only record usage for
// internal cost visibility. Map each endpoint to a human-readable description.
const ENDPOINT_DESCRIPTIONS: Record<string, string> = {
  "/analyze":                "Competitor analysis",
  "/score-page":             "Page scoring",
  "/generate-page":          "New page creation",
  "/reoptimize-page":        "Page reoptimization",
  "/check-rankability":      "Map pack check",
  "/generate-press-release": "Press release generation",
};

serve(async (req: Request) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders, status: 204 });
  }

  // Verify Supabase JWT
  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // Auth client — uses the user's JWT to identify them
  const authClient = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: { headers: { Authorization: authHeader } },
  });
  const { data: { user }, error: authError } = await authClient.auth.getUser();
  if (authError || !user) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // Extract the NLP endpoint from the URL path
  const url = new URL(req.url);
  const pathMatch = url.pathname.match(/\/nlp-proxy(\/.*)?$/);
  const endpoint = pathMatch?.[1] || "/";

  // Only allow POST to known endpoints
  const allowedEndpoints = [
    "/analyze", "/analyze-business", "/analyze-brand-voice",
    "/score-page", "/generate-page", "/reoptimize-page", "/reoptimize-section",
    "/find-page-for-keyword", "/related-pages", "/check-rankability",
    "/plan-pages", "/health", "/generate-social-posts",
    "/generate-press-release",
  ];
  if (!allowedEndpoints.includes(endpoint)) {
    return new Response(JSON.stringify({ error: "Not found" }), {
      status: 404,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // ── Usage logging (fire-and-forget, never blocks) ────────────────────────────
  // No credits/limits — internal tool. We just record who ran what.
  const description = ENDPOINT_DESCRIPTIONS[endpoint];
  if (description) {
    const adminClient = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
    adminClient
      .rpc("log_usage", { p_user_id: user.id, p_endpoint: endpoint, p_description: description })
      .then(({ error }: { error: unknown }) => {
        if (error) console.error("log_usage error:", error);
      });
  }

  // ── Forward request to NLP service ───────────────────────────────────────────
  try {
    const nlpResponse = await fetch(`${NLP_SERVICE_URL}${endpoint}`, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": NLP_API_KEY,
        "X-User-ID": user.id,
      },
      body: req.method !== "GET" ? req.body : undefined,
      // @ts-ignore - Deno supports duplex streaming
      duplex: "half",
    });

    // Forward the response (including streaming SSE responses)
    const responseHeaders = new Headers(corsHeaders);
    const contentType = nlpResponse.headers.get("Content-Type");
    if (contentType) responseHeaders.set("Content-Type", contentType);

    return new Response(nlpResponse.body, {
      status: nlpResponse.status,
      headers: responseHeaders,
    });
  } catch (err) {
    console.error("NLP proxy error:", err);
    return new Response(JSON.stringify({ error: "Service temporarily unavailable" }), {
      status: 502,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
