-- Allow 'expired' as a system decision value on the SerMaStr action log.
--
-- services/strategist_expiry.py auto-expires stale, un-actioned strategist
-- proposals; sermastr_audit.record_expired records that at SerMaStr's decision
-- seam like 'superseded' — a system state excluded from the approve/dismiss
-- learning rates. Without this the insert violated the existing CHECK
-- (approved/dismissed/superseded only) and the audit row was silently dropped.

alter table public.sermastr_action_log
  drop constraint if exists sermastr_action_log_decision_check;

alter table public.sermastr_action_log
  add constraint sermastr_action_log_decision_check
  check (decision = any (array['approved'::text, 'dismissed'::text,
                               'superseded'::text, 'expired'::text]));
