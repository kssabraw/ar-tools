-- Migration: 20260713010000_clients_ecommerce_page_template.sql
-- Purpose: House PDP template for the Ecommerce Writer. A per-client exemplar
--          product-page URL whose section layout/order/blocks the writer mirrors
--          on every PRODUCT generation, so all product descriptions follow the
--          client's fixed house structure. Mirrors clients.local_seo_page_template_url.
--          Products only (collections keep the default structure). Nullable —
--          absent = the writer's default PDP structure.

alter table clients
  add column if not exists ecommerce_page_template_url text;
