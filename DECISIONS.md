# DECISIONS.md

## What I chose and why

### 1. Provenance-first architecture
I modeled ingestion as two layers:
- `RawRecord` for immutable raw source data,
- `NormalizedRecord` for the cleaned, audited emissions row.

Why: this is the strongest source-of-truth model for ESG data because it preserves the original row even after correction, review, or reprocessing.

### 2. Multi-tenancy at the application layer
I used `TenantScopedManager` and explicit `tenant` foreign keys.

Why: it is simple, reliable for an MVP, and it makes the model clear. In production, I would add database row-level security.

### 3. Scope and category mapping
I defined `EmissionCategory` enums and derived scope values in parsers:
- SAP fuel → Scope 1,
- SAP electricity → Scope 2,
- procurement/fuel ambiguity → Scope 3,
- utility import → Scope 2,
- travel → Scope 3.

Why: this matches standard ESG reporting and keeps the model normalized.

### 4. Audit trail design
I made `AuditLogEntry` append-only and row-per-field.

Why: auditors need a precise history of what changed, not just a generic save event.

### 5. Unit normalization decisions
I normalized energy to `kWh`, mass to `kg`, distance to `km`, emissions to `tCO2e`.

Why: aggregating different unit types in a single column is unsafe; these normalized fields make reporting accurate and transparent.

## What subset of each source I handled

### SAP flat file
Handled a focused subset of SAP exports that include:
- quantity + unit,
- document/plant info,
- date,
- material description/vendor.

Ignored: SAP header languages beyond English/German, multi-currency conversion, and complex line item accounting data.

### Utility CSV
Handled billed electricity/energy export rows with:
- meter ID,
- period start/end,
- consumption and unit,
- read type,
- site/country.

Ignored: broad portfolio aggregation rows, demand/peak data, interval-level readings, and non-electricity utility types.

### Travel CSV
Handled typical Concur/Navan rows for:
- air,
- hotel,
- ground/rail travel.

Ignored: itinerary-level multi-leg grouping, separate tax lines, and proprietary corporate travel export variants.

## Ambiguities I resolved

### Tenant selection
I implemented a temporary `get_tenant(request)` that uses the first tenant.

Why: the app currently lacks full auth/tenant mapping, so this keeps the backend runnable while clearly signaling that auth is incomplete.

### Scope assignment for SAP rows
I treated `electricity` as Scope 2 and fuel as Scope 1.

Why: this is consistent with standard GHG Protocol guidance for purchased electricity versus direct fuel.

### Emission factor resolution
I used tenant-specific factors first, then global defaults, then country fallbacks.

Why: this supports client overrides while preserving a source-of-truth for the factor used.

## Questions for the PM

- Which tenant selection method should be used in production? API token, SSO, or per-user tenant assignment?
- Should the app support both location-based and market-based Scope 2 factors?
- Which source columns should be mandatory versus optional for each source type?
- Do we need to store original source filenames and full ingest metadata separately from `RawRecord`?
- Should the audit trail be exported to immutable archive storage after 90 days?

## Deployment decisions

- I chose combined deployment with Django serving the React frontend as static assets.

Why: this is easiest for a single URL submission and simplifies CORS / API routing.
