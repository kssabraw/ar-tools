# Enigma GraphQL API — focused reference (for the outreach Enigma rung)

Vendored subset of Enigma's GraphQL API reference (`documentation.enigma.com/reference/graphql_api/`),
kept because both Enigma doc hosts are egress-blocked from the dev sandbox. Public API docs — **no
secrets**. This is the contract the `probe-enigma-graphql` command + the future `enigma_request`
rung build against.

## Why GraphQL and not the REST match→ID path or the batch-file upload

- The REST `POST /businesses/match` → `GET /businesses/{id}?attrs=` path (see `enigma_client.py`,
  `probe-enigma`) returns identity + `data_sources` but, on the eval key, **returned no card block
  and no windows** — measured live 2026-08-27.
- The owner's manual CSV enrichment (Console **Batch Append**, ListType `ENRICHMENT`) *did* return
  card revenue + owner name — proving the account is entitled. Its output columns
  (`Card_revenue_amount_12M__0`, `operatingLocations__0__roles__0__legalEntities__0__persons__0__fullName__0`,
  `operatingLocations__0__Job_Title__0`, `…Management_Level__0`, `…Job_Function__0`,
  `…roles__0__Phone_Number__0`, `…roles__0__Email_Address__0`) map exactly onto the GraphQL schema
  paths below.
- The **GraphQL `search` query is synchronous per business** (a single small lookup returns
  immediately; only large `output`-file segmentation searches go async), so it drops straight into
  our per-prospect enrichment drain — same shape as the Outscraper `enrichment_request` rung — and,
  unlike the console batch, lets us request **all three 1m/3m/12m** windows, not just 12M.

## Endpoint + auth

- `POST https://api.enigma.com/graphql`
- Headers: `content-type: application/json`, `x-api-key: <API_KEY>`
- Body: `{"query": "<graphql>", "variables": {...}}`

## Matching a business (SearchInput)

`search(searchInput: SearchInput!)` returns `[SearchUnion]` = `Brand | OperatingLocation | LegalEntity`.
Match keys (any of): `name`, `address {street1, street2, city, state, postalCode}`, `person {firstName,
lastName, …}`, `phoneNumber` (`##########`), `website`. `matchThreshold` (0.0–1.0) gates confidence.
`entityType` defaults to `BRAND`. The owner's batch matched at BRAND level (columns start
`operatingLocations__0…`), so we mirror that: search `entityType: BRAND` by name+address, then
traverse `operatingLocations → roles`.

## The two payloads we want

### Card revenue windows (1m / 3m / 12m)  — `Brand.cardTransactions`

`BrandCardTransaction` fields: `quantityType` (we want `card_revenue_amount`), `period`
(`1m`|`3m`|`12m`), `projectedQuantity` (panel-scaled estimate — the headline $ figure; the console
export's `Card_revenue_amount_12M` is this at 12m), `rawQuantity`, `periodStartDate`, `periodEndDate`.
Other `quantityType`s exist (`card_revenue_yoy_growth`, `card_transactions_count`,
`avg_transaction_size`, `refunds_amount`, `card_customers_average_daily_count`,
`card_revenue_prior_period_growth`) — we scope to `card_revenue_amount` for the three windows.
`projectedQuantity` can be null when the underlying panel has too few transactions (compliance floor).

Filter form (from the docs' grocery example):
```
cardTransactions(conditions: { filter: { AND: [
  { EQ: ["quantityType", "card_revenue_amount"] },
  { IN: ["period", ["1m","3m","12m"]] }
] } }) { edges { node { period projectedQuantity rawQuantity periodStartDate periodEndDate } } }
```

### Owner / decision-maker  — `Brand.operatingLocations → roles`

`Role` fields: `jobTitle`, `jobFunction`, `managementLevel`, plus connections `phoneNumbers` →
`PhoneNumber.phoneNumber`, `emailAddresses` → `EmailAddress.emailAddress`, and `legalEntities` →
`LegalEntity`. The console batch's flattened path was
`operatingLocations__0__roles__0__legalEntities__0__persons__0__fullName__0`, **but the deployed
`search` schema rejects `Person.fullName`/`firstName`/`lastName`** (measured live 2026-08-27 — a
schema-validation 400). The name comes instead from `legalEntities → names → { name legalEntityType }`,
keeping only a `legalEntityType == "Person"` entity so a company legal-entity name is never mistaken
for an owner.

### Live-schema deviations from this doc's SDL (measured 2026-08-27)

The deployed `search` schema is slightly behind the published SDL. Two fields the SDL lists are
rejected with `Cannot query field '…'`:
- `BrandCardTransaction.rawQuantity` — Brand-level card transactions expose only `projectedQuantity`
  (`rawQuantity` exists on `OperatingLocationCardTransaction`, not Brand).
- `Person.fullName` / `firstName` / `lastName` — use `LegalEntity.names` instead (above).

## The probe query (BRAND match → owner + card windows)

```graphql
query Probe($si: SearchInput!) {
  search(searchInput: $si) {
    ... on Brand {
      enigmaId
      names(first: 1) { edges { node { name } } }
      cardTransactions(conditions: { filter: { AND: [
        { EQ: ["quantityType", "card_revenue_amount"] },
        { IN: ["period", ["1m", "3m", "12m"]] }
      ] } }) {
        edges { node { period projectedQuantity periodStartDate periodEndDate } }
      }
      operatingLocations(first: 1) {
        edges { node { roles(first: 3) { edges { node {
          jobTitle jobFunction managementLevel
          legalEntities(first: 2) { edges { node {
            names(first: 1) { edges { node { name legalEntityType } } }
          } } }
          phoneNumbers(first: 1) { edges { node { phoneNumber } } }
          emailAddresses(first: 1) { edges { node { emailAddress } } }
        } } } } }
      }
    }
  }
}
```
Variables: `{ "si": { "name": "<biz>", "entityType": "BRAND", "address": { "street1": "…", "city":
"…", "state": "…", "postalCode": "…" }, "matchThreshold": 0.7 } }`

## Async (only for big segmentation) + rate limits

A search with an `output` file spec returns `202` + `extensions.backgroundTasks[{id, status}]`;
poll `backgroundTask(id){status result}` until `SUCCESS` (terminal: `SUCCESS`/`FAILED`/`CANCELLED`),
then download the S3 URL in `result`. Our per-business lookups need **no** output spec, so they are
synchronous. `429 Slow Down` carries `Retry-After` (seconds) — honor it, cap retries.
