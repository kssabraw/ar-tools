-- Migration: 20260714020000_ecommerce_pages_notes.sql
-- Purpose: Per-page writing NOTES for the Ecommerce Writer. Free-text guidance the
--          user supplies at generate/reoptimize time (single or bulk) that the
--          writer follows as high-priority editorial instructions — e.g. "remove
--          the Research Use Only designation", "emphasize fast shipping", "target
--          clinics not individuals". Stored for provenance on the generated page.
--          Nullable; absent = default writing behavior.

alter table ecommerce_pages
  add column if not exists notes text;
