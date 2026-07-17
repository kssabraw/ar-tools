-- Migration: 20260717040000_ecommerce_pages_researched_facts.sql
-- Purpose: Store the invariant PUBLIC product specs the Ecommerce Writer
--          auto-researched (with citations) during generate/reoptimize — CAS
--          number, molecular weight/formula, amino-acid sequence, solubility,
--          reconstitution, stability, etc. — the compound-level facts that are
--          identical whoever sells the item and are documented in public
--          databases (PubChem/ChemSpider/DrugBank). These are written into the
--          page (and removed from CONTENT_GAPS), while VENDOR facts (price,
--          reviews, testing-lab identity, shipping, returns) stay gated to the
--          user. Persisted for provenance so the UI can show an
--          "auto-sourced — verify" panel with each value's source.
--          Shape: [{field, value, unit, source_name, source_url, confidence}].
--          Default '[]'; empty when research is disabled or found nothing citable.

alter table ecommerce_pages
  add column if not exists researched_facts jsonb not null default '[]'::jsonb;
