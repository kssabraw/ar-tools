-- The prospects feature (clients.kind='prospect') shipped without widening the
-- clients_kind_check CHECK constraint, which only allowed 'client'/'owned_property'
-- — so creating a prospect fails at the DB. Widen it to include 'prospect'.

alter table public.clients
  drop constraint if exists clients_kind_check;

alter table public.clients
  add constraint clients_kind_check
  check (kind = any (array['client'::text, 'prospect'::text, 'owned_property'::text]));
