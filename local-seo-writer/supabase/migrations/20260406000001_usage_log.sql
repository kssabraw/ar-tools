-- ── Usage log ─────────────────────────────────────────────────────────────────
-- Internal tool: no billing, no credits, no balances, no caps. This table is an
-- append-only record of who ran which (paid-API-backed) operation, kept only for
-- internal cost visibility. log_usage() always succeeds and never blocks an action.

CREATE TABLE IF NOT EXISTS public.usage_log (
  id          bigserial PRIMARY KEY,
  user_id     uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  endpoint    text NOT NULL,
  description text NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_log_user_created
  ON public.usage_log (user_id, created_at DESC);

ALTER TABLE public.usage_log ENABLE ROW LEVEL SECURITY;

-- Users can read their own usage; admins can read everyone's.
CREATE POLICY "Users read own usage"
  ON public.usage_log FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "Admins read all usage"
  ON public.usage_log FOR SELECT
  USING ((auth.jwt() ->> 'user_role') = 'admin');

-- ── log_usage() ───────────────────────────────────────────────────────────────
-- Records one usage row. SECURITY DEFINER so the service role (edge function /
-- NLP service) can insert on behalf of a user. Always succeeds; returns nothing.
CREATE OR REPLACE FUNCTION public.log_usage(
  p_user_id     uuid,
  p_endpoint    text,
  p_description text DEFAULT ''
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  INSERT INTO public.usage_log (user_id, endpoint, description)
  VALUES (p_user_id, p_endpoint, COALESCE(p_description, ''));
$$;
