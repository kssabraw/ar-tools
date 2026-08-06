-- Migration: 20260806120000_website_theme_bucket.sql
-- Purpose: Website Builder — private storage for uploaded Claude Design exports
--          and the files each compile produces.
--
--          Layout under the bucket:
--            <theme_id>/source/<filename>        the upload, kept verbatim so a
--                                                theme can be recompiled without
--                                                asking for the file again
--            <theme_id>/built/tokens.css         the compiled theme
--            <theme_id>/built/fonts/*.woff2      the families it self-hosts
--
--          The built files are committed into a site repo byte-for-byte, so what
--          ships is what was reviewed rather than a fresh compile that might
--          assign a role differently.
--
--          Private: a design is a client's brand before it is anyone else's
--          business, and reads go through the service role. 25 MB per file
--          matches website_theme_max_mb.

insert into storage.buckets (id, name, public, file_size_limit)
values ('website-themes', 'website-themes', false, 26214400)
on conflict (id) do nothing;
