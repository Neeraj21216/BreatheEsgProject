"""
SAP Flat-File Parser
====================
Handles CSV/TSV exports from SAP transaction MB51 (material movements)
and ME2N (purchase orders). Real SAP exports have:
  - German column headers in some configs (Menge=quantity, Werk=plant)
  - Dates as YYYYMMDD or DD.MM.YYYY
  - Units as SAP internal codes (L, KG, M3, GAL, TO)
  - Plant codes that need lookup to resolve to real locations
  - Semicolon delimiters common in German locale exports
"""

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from ingestion.models import (
    RawRecord, NormalizedRecord, AuditLogEntry,
    Scope, EmissionCategory, RecordStatus, FlagReason,
    EmissionFactor, PlantSite,
)

# ---------------------------------------------------------------------------
# SAP unit → normalized unit + conversion to kg or kWh
# ---------------------------------------------------------------------------

SAP_UNIT_MAP = {
    # Mass → kg
    "KG":  ("kg",   Decimal("1")),
    "G":   ("kg",   Decimal("0.001")),
    "TO":  ("kg",   Decimal("1000")),       # metric tonne
    "LB":  ("kg",   Decimal("0.453592")),
    # Volume → litres (fuel; we store as kg via density later)
    "L":   ("L",    Decimal("1")),
    "ML":  ("L",    Decimal("0.001")),
    "M3":  ("L",    Decimal("1000")),
    "GAL": ("L",    Decimal("3.78541")),
    # Energy → kWh
    "KWH": ("kWh",  Decimal("1")),
    "MWH": ("kWh",  Decimal("1000")),
    "GJ":  ("kWh",  Decimal("277.778")),
    "MJ":  ("kWh",  Decimal("0.277778")),
}

# Fuel type keywords → emission category
FUEL_KEYWORDS = {
    "diesel":       EmissionCategory.FUEL_MOBILE,
    "petrol":       EmissionCategory.FUEL_MOBILE,
    "gasoline":     EmissionCategory.FUEL_MOBILE,
    "benzin":       EmissionCategory.FUEL_MOBILE,   # German
    "natural gas":  EmissionCategory.FUEL_STATIONARY,
    "erdgas":       EmissionCategory.FUEL_STATIONARY,
    "lpg":          EmissionCategory.FUEL_STATIONARY,
    "coal":         EmissionCategory.FUEL_STATIONARY,
    "kohle":        EmissionCategory.FUEL_STATIONARY,
    "electricity":  EmissionCategory.ELECTRICITY,
    "strom":        EmissionCategory.ELECTRICITY,
}

# Column header aliases (EN and DE)
COLUMN_ALIASES = {
    # quantity
    "menge":             "quantity",
    "quantity":          "quantity",
    "qty":               "quantity",
    # unit
    "meins":             "unit",
    "base unit":         "unit",
    "unit":              "unit",
    "uom":               "unit",
    # date
    "bldat":             "date",
    "posting date":      "date",
    "document date":     "date",
    "budat":             "date",
    "date":              "date",
    # plant
    "werk":              "plant",
    "plant":             "plant",
    # material description
    "maktx":             "description",
    "material description": "description",
    "description":       "description",
    "text":              "description",
    # document number
    "mblnr":             "document_number",
    "material document": "document_number",
    "document number":   "document_number",
    # supplier
    "lifnr":             "supplier",
    "vendor":            "supplier",
    "supplier":          "supplier",
    # material code
    "matnr":             "material_code",
    "material":          "material_code",
    "material code":     "material_code",
    # cost
    "dmbtr":             "cost",
    "amount":            "cost",
    "cost":              "cost",
}


def _normalise_header(h: str) -> str:
    return COLUMN_ALIASES.get(h.strip().lower(), h.strip().lower())


def _parse_date(raw: str) -> datetime | None:
    for fmt in ("%Y%m%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _detect_fuel_type(description: str) -> tuple[str, str]:
    """Return (fuel_type_slug, EmissionCategory) from description text."""
    desc_lower = description.lower()
    for keyword, category in FUEL_KEYWORDS.items():
        if keyword in desc_lower:
            return keyword.replace(" ", "_"), category
    return "unknown", EmissionCategory.PROCUREMENT


def _detect_delimiter(content: bytes) -> str:
    sample = content[:2048].decode("utf-8", errors="replace")
    for delim in (";", ",", "\t", "|"):
        if delim in sample:
            return delim
    return ","


# ---------------------------------------------------------------------------
# Main entry point called from views.py
# ---------------------------------------------------------------------------

def parse_sap_file(file, job, tenant) -> dict:
    content = file.read()
    delimiter = _detect_delimiter(content)
    text = content.decode("utf-8-sig", errors="replace")   # strip BOM

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    total = parsed = failed = flagged = 0
    errors = []

    for i, row in enumerate(reader):
        total += 1
        # Normalise headers
        norm_row = {_normalise_header(k): v for k, v in row.items()}

        try:
            raw = RawRecord.objects.create(
                tenant=tenant,
                ingestion_job=job,
                row_index=i,
                raw_data=dict(row),
            )

            record, row_flags, row_errors = _build_normalized(norm_row, raw, tenant)

            if row_errors:
                failed += 1
                errors.extend([{"row": i, **e} for e in row_errors])
                raw.normalized = False
                raw.save(update_fields=["normalized"])
                continue

            record.flags = row_flags
            if row_flags:
                record.status = RecordStatus.FLAGGED
                flagged += 1

            record.save()
            raw.normalized = True
            raw.save(update_fields=["normalized"])
            parsed += 1

        except Exception as e:
            failed += 1
            errors.append({"row": i, "error": str(e), "raw": dict(row)})

    return {
        "total": total, "parsed": parsed,
        "failed": failed, "flagged": flagged,
        "errors": errors,
    }


def _build_normalized(row: dict, raw: RawRecord, tenant) -> tuple:
    flags = []
    errors = []
    now = timezone.now().date()

    # --- Quantity ---
    try:
        qty = Decimal(str(row.get("quantity", "")).replace(",", ".").strip())
    except InvalidOperation:
        errors.append({"field": "quantity", "raw_value": row.get("quantity"), "error": "Not a number"})
        return None, flags, errors

    if qty < 0:
        flags.append(FlagReason.NEGATIVE_VALUE)

    # --- Unit ---
    raw_unit = row.get("unit", "").strip().upper()
    if raw_unit not in SAP_UNIT_MAP:
        flags.append(FlagReason.UNIT_AMBIGUOUS)
        norm_unit, multiplier = raw_unit, Decimal("1")
    else:
        norm_unit, multiplier = SAP_UNIT_MAP[raw_unit]

    norm_qty = qty * multiplier

    # --- Date ---
    raw_date = row.get("date", "").strip()
    parsed_date = _parse_date(raw_date)
    if not parsed_date:
        errors.append({"field": "date", "raw_value": raw_date, "error": "Unrecognised date format"})
        return None, flags, errors

    # --- Plant / location ---
    plant_code = row.get("plant", "").strip()
    plant_site = None
    country = ""
    if plant_code:
        plant_site = PlantSite.objects.filter(tenant=tenant, sap_code=plant_code).first()
        if plant_site:
            country = plant_site.country
        else:
            flags.append(FlagReason.PLANT_UNKNOWN)

    # --- Fuel / category ---
    description = row.get("description", "")
    fuel_type, category = _detect_fuel_type(description)

    # Electricity from SAP = Scope 2, fuel = Scope 1, procurement = Scope 3
    if category == EmissionCategory.ELECTRICITY:
        scope = Scope.SCOPE_2
    elif category == EmissionCategory.PROCUREMENT:
        scope = Scope.SCOPE_3
    else:
        scope = Scope.SCOPE_1

    # --- Emission factor ---
    factor = EmissionFactor.resolve(
        category=category, country=country or "XX",
        date=parsed_date, tenant=tenant, fuel_type=fuel_type,
    )
    if not factor:
        flags.append(FlagReason.MISSING_FACTOR)

    # --- Build quantity fields ---
    quantity_kwh = norm_qty if norm_unit == "kWh" else None
    quantity_kg  = norm_qty if norm_unit == "kg"  else None
    # Litres stored as kg via rough diesel density (0.85 kg/L) if fuel
    if norm_unit == "L" and fuel_type != "unknown":
        quantity_kg = norm_qty * Decimal("0.85")

    co2e = None
    if factor and (quantity_kwh or quantity_kg):
        base = quantity_kwh or quantity_kg
        co2e = (base * factor.factor_value / Decimal("1000")).quantize(Decimal("0.000001"))

    record = NormalizedRecord(
        tenant=tenant,
        raw_record=raw,
        scope=scope,
        category=category,
        period_start=parsed_date,
        period_end=parsed_date,
        country=country,
        location_raw=plant_code,
        plant_site=plant_site,
        original_quantity=qty,
        original_unit=raw_unit,
        quantity_kwh=quantity_kwh,
        quantity_kg=quantity_kg,
        fuel_type=fuel_type,
        emission_factor=factor,
        co2e_tonnes=co2e,
        sap_document_number=row.get("document_number", ""),
        sap_material_code=row.get("material_code", ""),
        supplier_name=row.get("supplier", ""),
        status=RecordStatus.PENDING,
    )
    return record, flags, errors