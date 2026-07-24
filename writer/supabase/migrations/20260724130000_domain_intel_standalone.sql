-- Domain Intelligence: allow standalone (client-less) domain lookups.
--
-- The Domain lookup (overview + ranked keywords) doesn't need a client — it
-- just points at any domain. Standalone lookups are stored with client_id NULL,
-- forming a shared agency-wide research history (the paid-call budget meter is
-- already agency-global). Keyword-gap / discover stay client-scoped — they
-- compare a domain against a specific client's competitor set.
alter table domain_intel_snapshots alter column client_id drop not null;
