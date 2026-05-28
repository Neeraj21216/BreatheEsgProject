# MODEL.md

## Overview

This project models ESG emissions ingestion as a provenance-first, multi-tenant platform.
The central design is:
- preserve raw source rows as immutable truth,
- normalize emissions into a canonical record,
- maintain multi-tenant isolation,
- categorize records by Scope 1/2/3,
- track source provenance and edits,
- store normalized quantities in standard units,
- record an audit trail for every status or field change.

## Core tables

### Tenant
- `id` (UUID)
- `name`, `slug`
- `reporting_year_start`, `reporting_year_end`
- `is_active`

Purpose: one tenant = one client company. All ingestion and normalized records are scoped to a tenant.

### User
- extends `AbstractUser`
- `tenant` foreign key
- `is_analyst`, `is_uploader`

Purpose: tenant-specific users plus internal staff users (tenant=null).

### PlantSite
- `tenant`
- `sap_code`
- `name`, `country`, `region`, `city`
- optional GPS coordinates

Purpose: map SAP plant codes to real-world location metadata for emission factor selection.

### EmissionFactor
- `tenant` nullable (global default when null)
- `category`, `fuel_type`, `country`
- `valid_from`, `valid_to`
- `factor_value`, `factor_unit`
- `source`, `notes`

Purpose: versioned factor lookup with tenant-specific override. This supports source-of-truth retention by storing the factor row used for each calculation.

### IngestionJob
- `tenant`
- `source_type`
- `status`
- `file_name`, `file_path`, `file_hash`, `file_size`
- `created_by`, `created_at`, `started_at`, `finished_at`
- `total_rows`, `parsed_rows`, `failed_rows`, `flagged_rows`
- `parse_errors`
- `notes`

Purpose: one upload or pull event. Tracks source provenance at the file/job level and enables duplicate detection via hash.

### RawRecord
- `tenant`
- `ingestion_job`
- `row_index`
- `raw_data` JSON
- `normalized` boolean
- `created_at`

Purpose: immutable source row storage. This is the canonical source-of-truth for what was actually ingested.

### NormalizedRecord
- `tenant`
- `raw_record` one-to-one
- `scope` (1/2/3)
- `category`
- location fields: `plant_site`, `country`, `location_raw`
- period fields: `period_start`, `period_end`, `invoice_date`
- original source values: `original_quantity`, `original_unit`, `original_cost`, `original_currency`
- normalized measures: `quantity_kwh`, `quantity_kg`, `quantity_km`, `quantity_nights`
- travel metadata: `travel_origin`, `travel_destination`, `travel_class`, `vehicle_type`, `traveller_count`, `distance_method`
- SAP and utility metadata: `sap_document_number`, `sap_material_code`, `fuel_type`, `supplier_name`, `meter_id`, `tariff_code`, `is_estimated_read`
- emission calculation: `emission_factor`, `co2e_tonnes`, `co2e_calculation_notes`
- review state: `status`, `flags`, `flag_notes`
- review tracking: `reviewed_by`, `reviewed_at`, `locked_by`, `locked_at`
- timestamps: `created_at`, `updated_at`

Purpose: canonical, auditable emission record. It is normalized into standard units and only one record exists per meaningful activity row.

### AuditLogEntry
- `tenant`
- `record`
- `changed_by`
- `action`
- `field_name`
- `old_value`, `new_value`
- `notes`
- `timestamp`

Purpose: immutable append-only audit trail. Every status transition, flag action, approval, lock, or field change is recorded here.

## Multi-tenancy

Multi-tenancy is enforced by:
- `TenantScopedManager` on tenant-scoped models,
- storing `tenant` on every core data table,
- query filters in views such as `NormalizedRecord.objects.for_tenant(tenant)`.

This means tenant isolation is maintained in app logic, and a further production improvement would be PostgreSQL Row-Level Security.

## Scope 1/2/3 categorization

Categories are expressed as `EmissionCategory` choices and mapped to Scope values:
- `Scope 1` for direct fuel consumption and onsite combustion,
- `Scope 2` for purchased electricity/heat,
- `Scope 3` for travel and procurement-related emissions.

This supports reporting by scope and totals in the dashboard.

## Source-of-truth tracking

The system tracks provenance at multiple levels:
- `IngestionJob` records file metadata, source type, and processing outcome,
- `RawRecord` stores the exact parsed row JSON and row index,
- `NormalizedRecord` ties back to the `RawRecord` and stores the calculation outcome,
- the `EmissionFactor` used is stored on the normalized record,
- `AuditLogEntry` records all review actions and edits.

## Unit normalization

The model preserves original units and normalizes values into standard fields:
- energy → `quantity_kwh`
- mass → `quantity_kg`
- distance → `quantity_km`
- emissions → `co2e_tonnes`

Only the relevant normalized quantity is populated per record to avoid invalid cross-unit aggregation.

## Audit trail

Audit logging is row-level and append-only. The key elements are:
- immutable `AuditLogEntry` rows,
- status transitions (`PENDING`, `FLAGGED`, `APPROVED`, `LOCKED`),
- manual and automated flag reasons,
- review metadata for who approved or locked a record.

This supports compliance-oriented review and post-ingestion investigations.
