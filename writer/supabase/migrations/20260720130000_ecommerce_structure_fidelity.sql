-- Migration: 20260720130000_ecommerce_structure_fidelity.sql
-- Purpose: Persist the structural-fidelity verdict from the Ecommerce PRODUCT
--          generation gate (services/ecommerce_service._apply_structure_gate),
--          mirroring the Local SEO gate (20260720120000). The gate scores each
--          generated product page against the client's scraped
--          page_structures['product'] reference and attaches the verdict
--          ({composite, dimensions, notes}) to the result; this stores it.
--
--            1. ecommerce_pages.structure_fidelity        — current verdict.
--            2. ecommerce_page_scores.structure_fidelity  — per-run history.
--          Null on collections, on products driven by a house template (gate off),
--          and on reoptimize/standalone-score rows. Additive, nullable. RLS
--          unchanged (service-role only).

alter table ecommerce_pages
  add column if not exists structure_fidelity jsonb;

alter table ecommerce_page_scores
  add column if not exists structure_fidelity jsonb;
