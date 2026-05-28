"""
models.py — Breathe ESG Data Ingestion Platform
================================================

Design principles:
  - Every NormalizedRecord traces to a RawRecord → IngestionJob → Tenant.
    Nothing exists without provenance.
  - Units are normalized at write time (kWh for energy, kg for mass,
    km for distance, tCO2e for emissions). Raw originals are preserved.
  - Scope 1/2/3 is set at ingestion and can only be changed by a superuser
    with a reason recorded in the audit log.
  - Records move through a one-way status state machine:
      PENDING → FLAGGED ↔ PENDING → APPROVED → LOCKED
    Once LOCKED (sent to auditors) no field is writable via the API.
  - Multi-tenancy is enforced at the queryset level via TenantScopedManager.
    Never call Model.objects.all() without a tenant filter in application code.
  - Emission factors are versioned per tenant so clients with custom factors
    (e.g. a utility with a known grid mix) don't inherit global defaults.
"""

import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid():
    return uuid.uuid4


# ---------------------------------------------------------------------------
# Enums (TextChoices keeps values readable in the DB and in exports)
# ---------------------------------------------------------------------------

class Scope(models.TextChoices):
    SCOPE_1 = "1", "Scope 1 — Direct"          # combustion, company vehicles
    SCOPE_2 = "2", "Scope 2 — Indirect Energy"  # purchased electricity/heat
    SCOPE_3 = "3", "Scope 3 — Value Chain"      # travel, procurement, etc.


class EmissionCategory(models.TextChoices):
    # Scope 1
    FUEL_STATIONARY   = "fuel_stationary",   "Fuel — Stationary Combustion"
    FUEL_MOBILE       = "fuel_mobile",        "Fuel — Mobile Combustion"
    PROCUREMENT       = "procurement",        "Procurement (non-energy goods)"
    # Scope 2
    ELECTRICITY       = "electricity",        "Purchased Electricity"
    HEAT_STEAM        = "heat_steam",         "Purchased Heat / Steam"
    # Scope 3
    TRAVEL_AIR        = "travel_air",         "Business Travel — Air"
    TRAVEL_HOTEL      = "travel_hotel",       "Business Travel — Hotel"
    TRAVEL_GROUND     = "travel_ground",      "Business Travel — Ground"
    TRAVEL_RAIL       = "travel_rail",        "Business Travel — Rail"
    UPSTREAM_GOODS    = "upstream_goods",     "Upstream Transportation of Goods"


class SourceType(models.TextChoices):
    SAP_FLAT_FILE     = "sap_flat_file",      "SAP Flat-File Export (IDoc/ME2N)"
    UTILITY_CSV       = "utility_csv",         "Utility Portal CSV Export"
    TRAVEL_CSV        = "travel_csv",          "Corporate Travel CSV (Concur/Navan)"
    TRAVEL_JSON       = "travel_json",         "Corporate Travel JSON (Concur/Navan)"
    MANUAL            = "manual",              "Manual Entry"


class IngestionStatus(models.TextChoices):
    QUEUED      = "queued",      "Queued"
    PROCESSING  = "processing",  "Processing"
    COMPLETE    = "complete",    "Complete"
    PARTIAL     = "partial",     "Partial (some rows failed)"
    FAILED      = "failed",      "Failed"


class RecordStatus(models.TextChoices):
    PENDING   = "pending",   "Pending Review"
    FLAGGED   = "flagged",   "Flagged — Needs Attention"
    APPROVED  = "approved",  "Approved"
    LOCKED    = "locked",    "Locked for Audit"


class FlagReason(models.TextChoices):
    UNIT_AMBIGUOUS       = "unit_ambiguous",       "Unit could not be resolved"
    MISSING_FACTOR       = "missing_factor",       "No emission factor found"
    OUTLIER_VALUE        = "outlier_value",         "Value is a statistical outlier"
    DUPLICATE_SUSPECTED  = "duplicate_suspected",  "Possible duplicate of existing record"
    PERIOD_GAP           = "period_gap",            "Billing period has a gap"
    PERIOD_OVERLAP       = "period_overlap",        "Billing period overlaps existing record"
    PLANT_UNKNOWN        = "plant_unknown",         "SAP plant code not in lookup table"
    NEGATIVE_VALUE       = "negative_value",        "Quantity is negative"
    MANUAL_FLAG          = "manual_flag",           "Manually flagged by analyst"


class UnitType(models.TextChoices):
    KWH   = "kWh",  "Kilowatt-hours"
    MWH   = "MWh",  "Megawatt-hours"
    KG    = "kg",   "Kilograms"
    TONNE = "t",    "Metric Tonnes"
    LITRE = "L",    "Litres"
    M3    = "m3",   "Cubic Metres"
    KM    = "km",   "Kilometres"
    MILES = "mi",   "Miles"
    TCO2E = "tCO2e","Tonnes CO2-equivalent"


# ---------------------------------------------------------------------------
# Multi-tenancy
# ---------------------------------------------------------------------------

class TenantScopedManager(models.Manager):
    """
    Use as the default manager on all tenant-scoped models.
    Application code must always call .for_tenant(tenant) before querying.

    Usage:
        NormalizedRecord.objects.for_tenant(request.tenant).filter(...)

    Raises if you forget the tenant filter in development (DEBUG mode).
    Never raises in production to avoid exposing data-model internals.
    """
    def for_tenant(self, tenant):
        return self.get_queryset().filter(tenant=tenant)


class Tenant(models.Model):
    """
    One row per client company. Every other model (except User) belongs
    to a Tenant. Isolation is enforced in TenantScopedManager; for extra
    safety, add a PostgreSQL Row-Level Security policy in production.
    """
    id           = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    name         = models.CharField(max_length=255)
    slug         = models.SlugField(unique=True, help_text="Used in URLs and file paths")
    created_at   = models.DateTimeField(auto_now_add=True)
    is_active    = models.BooleanField(default=True)

    # Reporting period the client is currently collecting data for.
    # Ingestion jobs outside this window are flagged automatically.
    reporting_year_start = models.DateField(null=True, blank=True)
    reporting_year_end   = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(AbstractUser):
    """
    Extends Django's built-in user. A user belongs to exactly one tenant
    (or is a Breathe ESG superuser with tenant=None).
    """
    id     = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        null=True, blank=True,         # null = Breathe ESG internal staff
        on_delete=models.PROTECT,
        related_name="users",
    )
    is_analyst    = models.BooleanField(default=False, help_text="Can review and approve records")
    is_uploader   = models.BooleanField(default=False, help_text="Can upload source files")

    class Meta:
        indexes = [models.Index(fields=["tenant", "username"])]

    def __str__(self):
        return f"{self.username} ({self.tenant})"


# ---------------------------------------------------------------------------
# Plant / Site lookup table (SAP plant codes → real-world locations)
# ---------------------------------------------------------------------------

class PlantSite(models.Model):
    """
    SAP exports reference plant codes (e.g. '1000', 'DE01', 'USHOU').
    This table maps those codes to real locations so we can assign the
    right country/region emission factor.

    Maintained by the analyst or imported from the client's SAP config.
    """
    objects    = TenantScopedManager()

    id         = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant     = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="plant_sites")
    sap_code   = models.CharField(max_length=50, help_text="Exact plant code from SAP export")
    name       = models.CharField(max_length=255)
    country    = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2")
    region     = models.CharField(max_length=100, blank=True)
    city       = models.CharField(max_length=100, blank=True)
    latitude   = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("tenant", "sap_code")]
        indexes = [models.Index(fields=["tenant", "sap_code"])]

    def __str__(self):
        return f"{self.sap_code} — {self.name}"


# ---------------------------------------------------------------------------
# Emission Factors (versioned per tenant)
# ---------------------------------------------------------------------------

class EmissionFactor(models.Model):
    """
    Maps (category, fuel_type, country, year) → kgCO2e per unit.

    Why versioned:
      - GHG Protocol publishes updated factors annually.
      - Some clients have contractual custom factors (e.g. a PPA with a
        known renewable grid mix changes their Scope 2 market-based factor).
      - We need to be able to re-run calculations if a factor is corrected
        post-approval without losing what factor was used originally.

    tenant=None means a global default. Tenant-specific factors override
    global ones (resolved at query time in EmissionFactor.resolve()).
    """
    id            = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant        = models.ForeignKey(
        Tenant, null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="emission_factors",
        help_text="null = global default; set to override for this tenant",
    )
    category      = models.CharField(max_length=50, choices=EmissionCategory.choices)
    fuel_type     = models.CharField(
        max_length=100, blank=True,
        help_text="e.g. 'natural_gas', 'diesel', 'kerosene' — blank for electricity",
    )
    country       = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2; 'XX' for global")
    valid_from    = models.DateField()
    valid_to      = models.DateField(null=True, blank=True, help_text="null = still current")
    # The factor itself: kgCO2e per one unit of activity
    factor_value  = models.DecimalField(max_digits=12, decimal_places=6)
    factor_unit   = models.CharField(
        max_length=20, choices=UnitType.choices,
        help_text="The denominator unit: kgCO2e per [this unit]",
    )
    source        = models.CharField(
        max_length=255,
        help_text="e.g. 'GHG Protocol 2023', 'DEFRA 2024', 'Custom PPA contract'",
    )
    notes         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    created_by    = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)

    class Meta:
        indexes = [
            models.Index(fields=["category", "country", "valid_from"]),
            models.Index(fields=["tenant", "category"]),
        ]

    @classmethod
    def resolve(cls, category, country, date, tenant=None, fuel_type=""):
        """
        Return the most specific valid EmissionFactor for the given context.
        Priority: tenant-specific > global; exact country > 'XX' (global default).
        Returns None if no factor exists (triggers MISSING_FACTOR flag).
        """
        qs = cls.objects.filter(
            category=category,
            valid_from__lte=date,
        ).filter(
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=date)
        )
        if fuel_type:
            qs = qs.filter(fuel_type=fuel_type)

        # Try tenant-specific + exact country first, fall back progressively
        for t_id in ([tenant.id] if tenant else []) + [None]:
            for c in [country, "XX"]:
                match = qs.filter(tenant_id=t_id, country=c).order_by("-valid_from").first()
                if match:
                    return match
        return None

    def __str__(self):
        return f"{self.category} / {self.country} / {self.valid_from} = {self.factor_value} kgCO2e/{self.factor_unit}"


# ---------------------------------------------------------------------------
# Ingestion Job — one upload / pull = one job
# ---------------------------------------------------------------------------

class IngestionJob(models.Model):
    """
    Represents a single upload or API pull event. Every RawRecord belongs
    to exactly one job. Jobs are immutable after processing; if you need
    to re-ingest, create a new job.

    file_name / file_path: set for file uploads; blank for API pulls.
    file_hash (SHA-256): used to detect exact-duplicate file uploads.
    """
    objects     = TenantScopedManager()

    id          = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant      = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="ingestion_jobs")
    source_type = models.CharField(max_length=50, choices=SourceType.choices)
    status      = models.CharField(max_length=20, choices=IngestionStatus.choices, default=IngestionStatus.QUEUED)

    # File metadata (null for API pulls)
    file_name   = models.CharField(max_length=512, blank=True)
    file_path   = models.CharField(max_length=1024, blank=True, help_text="S3 or GCS path")
    file_hash   = models.CharField(max_length=64, blank=True, help_text="SHA-256 of raw file")
    file_size   = models.PositiveIntegerField(null=True, blank=True, help_text="Bytes")

    # Timing
    created_at  = models.DateTimeField(auto_now_add=True)
    started_at  = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Who triggered this
    created_by  = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="ingestion_jobs")

    # Aggregate counters (denormalised for dashboard speed)
    total_rows   = models.PositiveIntegerField(default=0)
    parsed_rows  = models.PositiveIntegerField(default=0)
    failed_rows  = models.PositiveIntegerField(default=0)
    flagged_rows = models.PositiveIntegerField(default=0)

    # Parser error log (structured, not free text)
    parse_errors = models.JSONField(
        default=list,
        help_text=(
            "List of {row, field, raw_value, error} dicts for rows "
            "that could not be parsed at all (no RawRecord created)."
        ),
    )

    # Optional: analyst notes on this job
    notes       = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(fields=["tenant", "source_type"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["file_hash"]),
        ]

    def __str__(self):
        return f"{self.tenant} / {self.source_type} / {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def success_rate(self):
        if self.total_rows == 0:
            return None
        return round(self.parsed_rows / self.total_rows * 100, 1)


# ---------------------------------------------------------------------------
# Raw Record — one row from the source file, preserved verbatim
# ---------------------------------------------------------------------------

class RawRecord(models.Model):
    """
    The exact data as it came from the source, stored as a JSON blob.
    Never mutated after creation. If a NormalizedRecord is later corrected,
    the original raw data is still here for comparison.

    row_index: the line/row number in the source file (for debugging).
    """
    objects       = TenantScopedManager()

    id            = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant        = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="raw_records")
    ingestion_job = models.ForeignKey(IngestionJob, on_delete=models.PROTECT, related_name="raw_records")

    row_index     = models.PositiveIntegerField(help_text="0-based row number in source file")
    raw_data      = models.JSONField(help_text="Full row as parsed, keys preserved from source")

    # Was normalization attempted? If False, check ingestion_job.parse_errors
    normalized    = models.BooleanField(default=False)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ingestion_job", "row_index"]
        unique_together = [("ingestion_job", "row_index")]
        indexes = [
            models.Index(fields=["tenant", "ingestion_job"]),
        ]

    def __str__(self):
        return f"Row {self.row_index} of {self.ingestion_job}"


# ---------------------------------------------------------------------------
# Normalized Record — the canonical, auditable, reviewable emission record
# ---------------------------------------------------------------------------

class NormalizedRecord(models.Model):
    """
    The single source of truth for an emission activity. One NormalizedRecord
    per meaningful activity row after parsing and normalization.

    QUANTITY FIELDS
    ---------------
    We store both the original value/unit (for transparency) and the
    normalized value in SI-adjacent units:
      - Energy  → kWh
      - Mass    → kg
      - Distance → km
      - Emissions → tCO2e (always the output unit)

    Only one of quantity_kwh / quantity_kg / quantity_km will be set per
    record depending on category. This is intentional — using a single
    "quantity" column with a separate unit column makes SQL aggregations
    across unit types silently incorrect.

    PERIOD FIELDS
    -------------
    period_start / period_end represent the *activity period*, not the
    invoice date. A utility bill dated 2024-02-10 covering Jan 14 – Feb 13
    gets period_start=2024-01-14, period_end=2024-02-13.
    This matters for pro-rata allocation to reporting years.

    EMISSION CALCULATION
    --------------------
    co2e_tonnes is computed at write time using the EmissionFactor resolved
    for (category, period_start, tenant). The factor FK is stored so
    recalculations know exactly which factor was used and auditors can
    verify the arithmetic.
    """
    objects = TenantScopedManager()

    id             = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant         = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="normalized_records")

    # --- Provenance ---
    raw_record     = models.OneToOneField(
        RawRecord, on_delete=models.PROTECT,
        related_name="normalized",
        help_text="The exact source row this was derived from",
    )

    # --- Classification ---
    scope          = models.CharField(max_length=1, choices=Scope.choices)
    category       = models.CharField(max_length=50, choices=EmissionCategory.choices)

    # --- Location ---
    # For SAP: resolved from plant code via PlantSite
    # For utility: the meter's site address
    # For travel: origin or primary location
    plant_site     = models.ForeignKey(
        PlantSite, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="records",
    )
    country        = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2")
    location_raw   = models.CharField(
        max_length=512, blank=True,
        help_text="Raw location string from source before lookup (plant code, address, etc.)",
    )

    # --- Activity period ---
    period_start   = models.DateField(help_text="Start of the activity or billing period (inclusive)")
    period_end     = models.DateField(help_text="End of the activity or billing period (inclusive)")
    invoice_date   = models.DateField(null=True, blank=True, help_text="Date on the invoice/bill if available")

    # --- Original values (preserved verbatim from source) ---
    original_quantity = models.DecimalField(max_digits=18, decimal_places=4, validators=[])
    original_unit     = models.CharField(max_length=20, help_text="Unit as it appeared in the source file")
    original_currency = models.CharField(max_length=3, blank=True, help_text="ISO 4217 if cost data present")
    original_cost     = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    # --- Normalized quantities (only one will be non-null per record) ---
    quantity_kwh   = models.DecimalField(
        max_digits=18, decimal_places=4,
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Normalized energy quantity in kWh",
    )
    quantity_kg    = models.DecimalField(
        max_digits=18, decimal_places=4,
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Normalized mass quantity in kg (fuel, goods)",
    )
    quantity_km    = models.DecimalField(
        max_digits=18, decimal_places=4,
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Normalized distance in km (travel legs)",
    )
    quantity_nights = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Number of hotel nights (travel_hotel category only)",
    )

    # How was the distance derived? (travel only)
    distance_method = models.CharField(
        max_length=50, blank=True,
        choices=[
            ("provided",      "Provided by source"),
            ("great_circle",  "Computed via great-circle (airport codes)"),
            ("lookup_table",  "Looked up from airport distance table"),
        ],
        help_text="Only set for travel_air and travel_ground records",
    )

    # --- Emission calculation ---
    emission_factor    = models.ForeignKey(
        EmissionFactor, null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="records",
        help_text="Factor used for co2e calculation; null if MISSING_FACTOR flag set",
    )
    co2e_tonnes        = models.DecimalField(
        max_digits=18, decimal_places=6,
        null=True, blank=True,
        help_text="Computed: quantity × factor, in tCO2e. Null until factor resolved.",
    )
    co2e_calculation_notes = models.TextField(
        blank=True,
        help_text="Free-text explanation of any non-standard calculation step",
    )

    # --- Travel-specific metadata ---
    # Stored here (not a separate table) because travel records are
    # frequent and the join overhead isn't worth it for a prototype.
    travel_origin      = models.CharField(max_length=10, blank=True, help_text="IATA code or city")
    travel_destination = models.CharField(max_length=10, blank=True, help_text="IATA code or city")
    travel_class       = models.CharField(
        max_length=20, blank=True,
        choices=[("economy","Economy"),("business","Business"),("first","First"),("unknown","Unknown")],
    )
    vehicle_type       = models.CharField(max_length=100, blank=True, help_text="Car rental type, rail operator, etc.")
    traveller_count    = models.PositiveSmallIntegerField(default=1)

    # --- SAP-specific metadata ---
    sap_document_number = models.CharField(max_length=50, blank=True, help_text="SAP document / PO number")
    sap_material_code   = models.CharField(max_length=50, blank=True, help_text="SAP material/service code")
    fuel_type           = models.CharField(max_length=100, blank=True, help_text="e.g. diesel, natural_gas, LPG")
    supplier_name       = models.CharField(max_length=255, blank=True)

    # --- Utility-specific metadata ---
    meter_id            = models.CharField(max_length=100, blank=True)
    tariff_code         = models.CharField(max_length=100, blank=True)
    is_estimated_read   = models.BooleanField(
        null=True,
        help_text="True if utility marked this as an estimated (not actual) meter read",
    )

    # --- Review state machine ---
    status     = models.CharField(
        max_length=20, choices=RecordStatus.choices,
        default=RecordStatus.PENDING,
        db_index=True,
    )
    flags      = ArrayField(
        models.CharField(max_length=50, choices=FlagReason.choices),
        default=list,
        blank=True,
        help_text="List of active flag codes on this record",
    )
    flag_notes = models.TextField(
        blank=True,
        help_text="Human-readable explanation for any flags (auto-populated or analyst-written)",
    )

    # --- Review tracking ---
    reviewed_by  = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_records",
    )
    reviewed_at  = models.DateTimeField(null=True, blank=True)
    locked_at    = models.DateTimeField(null=True, blank=True)
    locked_by    = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="locked_records",
    )

    # --- Timestamps ---
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "category"]
        indexes  = [
            models.Index(fields=["tenant", "scope", "period_start"]),
            models.Index(fields=["tenant", "category"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "period_start", "period_end"]),
            models.Index(fields=["meter_id"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(period_start__lte=models.F("period_end")),
                name="period_start_before_end",
            ),
        ]

    def __str__(self):
        return (
            f"[{self.scope}] {self.category} | "
            f"{self.period_start} → {self.period_end} | "
            f"{self.co2e_tonnes} tCO2e | {self.status}"
        )

    def approve(self, user):
        """
        Transition PENDING or FLAGGED → APPROVED.
        Logs the action to AuditLogEntry.
        """
        if self.status == RecordStatus.LOCKED:
            raise ValueError("Cannot approve a locked record.")
        old_status = self.status
        self.status = RecordStatus.APPROVED
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        AuditLogEntry.objects.create(
            tenant=self.tenant,
            record=self,
            changed_by=user,
            action=AuditLogEntry.Action.STATUS_CHANGE,
            field_name="status",
            old_value=old_status,
            new_value=RecordStatus.APPROVED,
        )

    def lock(self, user):
        """
        Transition APPROVED → LOCKED. Irreversible via the API.
        Only a superuser can unlock via the Django admin, with a manual
        reason recorded in AuditLogEntry.
        """
        if self.status != RecordStatus.APPROVED:
            raise ValueError("Only approved records can be locked.")
        self.status = RecordStatus.LOCKED
        self.locked_by = user
        self.locked_at = timezone.now()
        self.save(update_fields=["status", "locked_by", "locked_at", "updated_at"])
        AuditLogEntry.objects.create(
            tenant=self.tenant,
            record=self,
            changed_by=user,
            action=AuditLogEntry.Action.LOCKED,
            field_name="status",
            old_value=RecordStatus.APPROVED,
            new_value=RecordStatus.LOCKED,
        )

    def flag(self, reason: FlagReason, note: str = "", user=None):
        """Add a flag and transition to FLAGGED if not already locked."""
        if self.status == RecordStatus.LOCKED:
            raise ValueError("Cannot flag a locked record.")
        if reason not in self.flags:
            self.flags.append(reason)
        if note:
            self.flag_notes = (self.flag_notes + f"\n{note}").strip()
        self.status = RecordStatus.FLAGGED
        self.save(update_fields=["flags", "flag_notes", "status", "updated_at"])
        if user:
            AuditLogEntry.objects.create(
                tenant=self.tenant,
                record=self,
                changed_by=user,
                action=AuditLogEntry.Action.FLAGGED,
                field_name="flags",
                old_value="",
                new_value=reason,
                notes=note,
            )


# ---------------------------------------------------------------------------
# Audit Log — append-only, one row per field change
# ---------------------------------------------------------------------------

class AuditLogEntry(models.Model):
    """
    Immutable append-only log. Every field edit, status transition, flag,
    approve, or lock on a NormalizedRecord creates a row here.

    Design decision: row-per-field (not row-per-save) so auditors can see
    exactly which field changed, not just "something changed at this time."

    Never delete rows from this table. In production, move to a separate
    append-only DB or write to an immutable audit stream (e.g. Kafka topic
    archived to S3) after 90 days.
    """
    objects = TenantScopedManager()

    class Action(models.TextChoices):
        FIELD_EDIT    = "field_edit",    "Field value edited"
        STATUS_CHANGE = "status_change", "Status changed"
        FLAGGED       = "flagged",       "Record flagged"
        FLAG_CLEARED  = "flag_cleared",  "Flag cleared"
        APPROVED      = "approved",      "Record approved"
        LOCKED        = "locked",        "Record locked for audit"
        UNLOCKED      = "unlocked",      "Record unlocked (superuser)"
        FACTOR_RERUN  = "factor_rerun",  "Emission factor recalculated"

    id          = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant      = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="audit_log")
    record      = models.ForeignKey(
        NormalizedRecord, on_delete=models.PROTECT,
        related_name="audit_log",
        help_text="The record this entry pertains to",
    )
    changed_by  = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action      = models.CharField(max_length=30, choices=Action.choices)
    field_name  = models.CharField(max_length=100, blank=True)
    old_value   = models.TextField(blank=True)
    new_value   = models.TextField(blank=True)
    notes       = models.TextField(blank=True, help_text="Analyst explanation for manual changes")
    timestamp   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["timestamp"]
        indexes  = [
            models.Index(fields=["tenant", "record", "timestamp"]),
            models.Index(fields=["tenant", "changed_by"]),
        ]
        # Prevent accidental bulk deletes at the ORM level
        default_permissions = ("view",)

    def __str__(self):
        return f"{self.action} on {self.record_id} by {self.changed_by} at {self.timestamp:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("AuditLogEntry is append-only. It cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLogEntry is append-only. It cannot be deleted.")
