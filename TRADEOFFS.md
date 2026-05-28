# TRADEOFFS.md

## Three deliberate scope cuts

### 1. No production-grade tenant isolation at the database layer
I chose app-layer tenant filtering with `TenantScopedManager` rather than building PostgreSQL Row-Level Security.

Why: it keeps the MVP focused on the model and ingestion flow. In production, RLS should still be added for stronger guarantees.

### 2. No full travel itinerary splitting
I did not build a complete multi-leg travel itinerary parser or a separate leg/segment model.

Why: for a prototype, the most important capability is getting travel emissions into the normalized model reliably. Advanced itinerary logic would add complexity without improving the core source-of-truth model.

### 3. No full source format coverage
I intentionally supported a narrow, realistic subset of each source type rather than every possible export variant.

Why: handling SAP, utility, and travel well is more valuable than building brittle support for dozens of corner-case export schemas.

## What I also deferred

- I did not build a full tenant-aware auth/role system with SSO.
- I did not implement export/report generation beyond dashboard summary stats.
- I did not build continuous reconciliation or deduplication beyond file-hash detection.
