-- Migration: 20260629220000_business_type.sql
-- Purpose: Track GBP business type — SAB (service-area business) / physical
--          (storefront) / hybrid — for the client and its competitors (Maps
--          strategy PRD, Tier B). Derived deterministically from the GBP payload
--          (a street address ⇒ physical; published service-area places ⇒ serves
--          areas; both ⇒ hybrid). Stored alongside the competitor GBP capture
--          and on the Local Relevance Scorecard rows.

alter table competitor_gbp_profiles add column if not exists business_type text;
alter table local_relevance_scores  add column if not exists business_type text;
