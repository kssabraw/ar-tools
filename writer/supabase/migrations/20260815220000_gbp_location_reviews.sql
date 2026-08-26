-- Individual GBP reviews (first-party, from the Google My Business v4 reviews API)
-- per location, for the GBP Insights dashboard's "reviews this period" panel.
-- One row per location×review; create_time is the absolute post date used to
-- window reviews to a reporting period. Refreshed by the daily 'gbp_reviews' job
-- (delete-then-insert per location, so Google-side deletions are reflected).
create table if not exists public.gbp_location_reviews (
  location_row_id uuid not null references public.gbp_locations(id) on delete cascade,
  review_id text not null,
  reviewer text not null default '',
  rating int,                       -- 1..5, null when unspecified
  text text not null default '',
  create_time timestamptz,          -- absolute post time (v4 createTime)
  update_time timestamptz,
  has_reply boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (location_row_id, review_id)
);

create index if not exists gbp_location_reviews_loc_created_idx
  on public.gbp_location_reviews (location_row_id, create_time desc);

alter table public.gbp_location_reviews enable row level security;
