-- Seed a LinkedIn platform spec so the Social module enforces it like the other
-- v1 platforms. LinkedIn accounts are already connectable via PostPeer, but had
-- no backend `social_platform_specs` row, so its limits were advisory-only
-- (frontend hint) and never enforced by `validate_post`. Feed posts only —
-- LinkedIn has no reels/stories.
insert into social_platform_specs (platform, char_limit, max_images, image_aspect_ratios, requires_image, link_policy, notes)
values
  ('linkedin', 3000, 9, '["1.91:1","1:1","4:5"]'::jsonb, false, 'allowed',
     'LinkedIn: 3,000 chars; up to 9 images or 1 video; feed posts only (no reels/stories); mentions are org-only.')
on conflict (platform) do nothing;
