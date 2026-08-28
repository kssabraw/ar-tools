-- Per-client SerMastr strategist opt-out.
--
-- Agency-owned website properties (clients.kind='owned_property') are real client
-- rows so the generators work, but they are not clients — running the owner-facing
-- strategist (weekly reviews + the ~monthly opportunity sweep) on a rank-and-rent
-- or PBN site is noise. This flag gates the SCHEDULED strategist pass (and the
-- escalation hooks); an explicit on-demand run is still allowed.
--
-- Default true so every existing client is unchanged; properties are minted with
-- it false (excluded), and the site's Settings tab can toggle one back in.
alter table clients
  add column if not exists strategist_enabled boolean not null default true;
