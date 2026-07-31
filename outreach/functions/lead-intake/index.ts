// lead-intake — inbound lead capture for the Phase 1b CRM.
//
// Deployed to the Outreacher project. Accepts a POST from a website form or
// webhook, normalizes it, and inserts a `source='inbound'` lead owned by nobody
// (it lands in the shared pool for someone to claim).
//
// Two things it deliberately does NOT do:
//   * check suppression — that is a BEFORE INSERT trigger on `lead`, so no
//     write path can skip it, including this one and a hand-written SQL insert.
//   * reject a suppressed lead — the trigger flags it. Dropping an inbound lead
//     because a stale suppression matched is unrecoverable; a flagged row is
//     visible and reversible.
//
// Auth is a shared secret, not a JWT: the callers are forms and webhooks, not
// signed-in users. verify_jwt is therefore off, and this header check is the
// only gate — so it fails closed if the secret is unset.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const SECRET = Deno.env.get("LEAD_INTAKE_SECRET");
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  // Fail closed. An unset secret must not mean "no auth required" — that is the
  // failure mode where a misconfigured deploy quietly becomes an open endpoint.
  if (!SECRET) {
    console.error("LEAD_INTAKE_SECRET is not set; refusing all requests");
    return json({ error: "not_configured" }, 503);
  }
  if (req.headers.get("x-intake-secret") !== SECRET) {
    return json({ error: "unauthorized" }, 401);
  }

  let payload: Record<string, unknown>;
  try {
    payload = await req.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }

  const str = (k: string) => {
    const v = payload[k];
    return typeof v === "string" && v.trim() !== "" ? v.trim() : null;
  };

  const business_name = str("business_name") ?? str("company") ?? str("name");
  const email = str("email");
  const phone = str("phone");

  // Something has to identify the lead or it is not actionable.
  if (!business_name && !email && !phone) {
    return json({ error: "insufficient_detail" }, 422);
  }

  const supabase = createClient(SUPABASE_URL, SERVICE_KEY);

  const { data, error } = await supabase
    .from("lead")
    .insert({
      source: "inbound",
      business_name,
      contact_name: str("contact_name"),
      email,
      phone,
      website: str("website"),
      city: str("city"),
      state: str("state"),
      postal_code: str("postal_code"),
      country: str("country"),
      category: str("category"),
      notes: str("message") ?? str("notes"),
      intake_channel: str("form") ?? str("source") ?? "webhook",
      intake_payload: payload, // kept verbatim: the raw body is the evidence
    })
    .select("id, suppressed_at, suppression_reason")
    .single();

  if (error) {
    console.error("lead insert failed", error);
    return json({ error: "insert_failed" }, 500);
  }

  // The caller is told it was accepted either way. A suppressed lead is still
  // recorded; whether to act on it is a human decision, not the form's.
  return json({
    id: data.id,
    suppressed: data.suppressed_at !== null,
    suppression_reason: data.suppression_reason,
  }, 201);
});
