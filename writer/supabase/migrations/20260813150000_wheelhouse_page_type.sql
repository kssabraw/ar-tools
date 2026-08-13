-- WheelHouse page poster — support BOTH shapes off one engine:
--   page_type='service' → State→City→Service, /florida/miami/managed-it/ (leaf = service)
--   page_type='city'    → State→City,         /florida/miami/           (leaf = city page,
--                         "[City] IT Support Company", service stored empty)
-- The city page is content-bearing AND the parent of the service pages beneath it.
alter table wheelhouse_pages
  add column if not exists page_type text not null default 'service'
    check (page_type in ('service', 'city'));

-- Include page_type in the live-row uniqueness so a city page (service '') and a
-- service page can't collide, and one row exists per (client, state, city,
-- service, page_type).
drop index if exists wheelhouse_pages_client_combo_uniq;
create unique index if not exists wheelhouse_pages_client_combo_uniq
  on wheelhouse_pages (client_id, state_slug, city_slug, service_slug, page_type)
  where deleted_at is null;
