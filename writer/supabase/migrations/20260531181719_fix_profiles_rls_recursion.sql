-- Fix infinite recursion in profiles RLS (Postgres 42P17).
--
-- The "admins read all profiles" / "admins update profiles" policies checked
-- admin status with an inline `EXISTS (SELECT 1 FROM profiles ...)`. Because
-- that subquery reads `profiles`, it re-triggers the same policies, so Postgres
-- aborts EVERY authenticated read of profiles with:
--   42P17: infinite recursion detected in policy for relation "profiles"
-- Net effect: the frontend's own-profile fetch failed, isAdmin was always
-- false, and admin-only UI (Add Client, edit/archive) was hidden from admins.
--
-- Fix: resolve admin status in a SECURITY DEFINER function that reads profiles
-- WITHOUT re-triggering RLS, and reference it from the policies.

CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.profiles
    WHERE id = auth.uid() AND role = 'admin'
  );
$$;

REVOKE EXECUTE ON FUNCTION public.is_admin() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_admin() TO authenticated;

-- Recreate the recursive policies using the helper.
DROP POLICY IF EXISTS "admins read all profiles" ON public.profiles;
CREATE POLICY "admins read all profiles"
  ON public.profiles FOR SELECT
  USING (public.is_admin());

DROP POLICY IF EXISTS "admins update profiles" ON public.profiles;
CREATE POLICY "admins update profiles"
  ON public.profiles FOR UPDATE
  USING (public.is_admin());

-- "users read own profile" (auth.uid() = id) is non-recursive and stays as-is.
