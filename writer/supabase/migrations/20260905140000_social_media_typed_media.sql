-- Social Media publish path: typed media (image AND video) on drafts.
-- image_urls (text[]) stays for back-compat; media (jsonb list of {type,url})
-- is the general path so a draft can carry a video (Facebook video / IG Reel)
-- or a mixed set, not just images. Additive.
alter table social_drafts
  add column if not exists media jsonb not null default '[]'::jsonb;
