"""
Utility Portal CSV Parser
=========================
Handles electricity CSV exports from utility portals (e.g. Octopus, EDF,
ENGIE self-service portals). Key real-world quirks handled:
  - Billing periods that don't align with calendar months
  - kWh / MWh / kVAh unit variants
  - Estimated vs actual meter reads (flagged)
  - Multiple meters per file (grouped by meter_id)
  - Missing or malformed period end dates
"""

import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from ingestion.models import (
    RawRecord, NormalizedRecord, RecordStatus, FlagReason,
    Scope, EmissionCategory, EmissionFactor,
)

COLUMN_ALIASES = {
    "meter id":           "meter_id",
    "meter_id":           "meter_id",
    "mpan":               "meter_id",
    "meter number":       "meter_id",
    "account number":     "meter_id",
    "period start":       "period_start",
    "period_start":       "period_start",
    "from":               "period_start",
    "start date":         "period_start",
    "period end":         "period_end",
    "period_end":         "period_end",
    "to":                 "period_end",
    "end date":           "period_end",
    "consumption":        "quantity",
    "usage":              "quantity",
    "kwh":                "quantity",
    "units consumed":     "quantity",
    "quantity":           "quantity",
    "unit":               "unit",
    "units":              "unit",
    "uom":                "unit",
    "read type":          "read_type",
    "read_type":          "read_type",
    "type":               "read_type",
    "site":               "site",
    "site name":          "site",
    "location":           "site",
    "address":            "site",
    "tariff":             "tariff",
    "tariff code":        "tariff",
    "rate":               "tariff",
    "cost":               "cost",
    "amount":             "cost",
    "total":              "cost",
    "invoice date":       "invoice_date",
    "bill date":          "invoice_date",
    "country":            "country",
}

UNIT_TO_KWH = {
    "KWH":  Decimal("1"),
    "MWH":  Decimal("1000"),
    "KVAH": Decimal("1"),       # treat kVAh ≈ kWh (approximate, flag not set here)
    "GJ":   Decimal("277.778"),
    "MJ":   Decimal("0.277778"),
}


def _norm_header(h):
    return COLUMN_ALIASES.get(h.strip().lower(), h.strip().lower())


def _parse_date(s):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_utility_file(file, job, tenant) -> dict:
    content = file.read()
    # Detect delimiter
    sample = content[:2048].decode("utf-8", errors="replace")
    delimiter = "," if sample.count(",") >= sample.count(";") else ";"

    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    total = parsed = failed = flagged = 0
    errors = []

    for i, row in enumerate(reader):
        total += 1
        norm_row = {_norm_header(k): v for k, v in row.items()}

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
            errors.append({"row": i, "error": str(e)})

    return {"total": total, "parsed": parsed, "failed": failed, "flagged": flagged, "errors": errors}


def _build_normalized(row, raw, tenant):
    flags = []
    errors = []

    # --- Quantity ---
    try:
        qty = Decimal(str(row.get("quantity", "")).replace(",", "").strip())
    except InvalidOperation:
        errors.append({"field": "quantity", "raw_value": row.get("quantity"), "error": "Not a number"})
        return None, flags, errors

    if qty < 0:
        flags.append(FlagReason.NEGATIVE_VALUE)

    # --- Unit → kWh ---
    raw_unit = row.get("unit", "KWH").strip().upper()
    multiplier = UNIT_TO_KWH.get(raw_unit)
    if not multiplier:
        flags.append(FlagReason.UNIT_AMBIGUOUS)
        multiplier = Decimal("1")
    quantity_kwh = qty * multiplier

    # --- Dates ---
    period_start = _parse_date(row.get("period_start", ""))
    period_end   = _parse_date(row.get("period_end", ""))
    invoice_date = _parse_date(row.get("invoice_date", "")) if row.get("invoice_date") else None

    if not period_start:
        errors.append({"field": "period_start", "raw_value": row.get("period_start"), "error": "Unrecognised date"})
        return None, flags, errors

    # If period_end missing, estimate it as 30 days after start
    if not period_end:
        period_end = period_start + timedelta(days=30)
        flags.append(FlagReason.PERIOD_GAP)

    if period_start > period_end:
        flags.append(FlagReason.PERIOD_OVERLAP)

    # --- Estimated read? ---
    read_type = row.get("read_type", "").strip().lower()
    is_estimated = read_type in ("e", "estimated", "est", "i", "inferred")

    # --- Emission factor (Scope 2 electricity) ---
    country = row.get("country", "XX").strip().upper() or "XX"
    factor = EmissionFactor.resolve(
        category=EmissionCategory.ELECTRICITY,
        country=country,
        date=period_start,
        tenant=tenant,
    )
    if not factor:
        flags.append(FlagReason.MISSING_FACTOR)

    co2e = None
    if factor:
        co2e = (quantity_kwh * factor.factor_value / Decimal("1000")).quantize(Decimal("0.000001"))

    # --- Cost ---
    cost = None
    if row.get("cost"):
        try:
            cost = Decimal(str(row["cost"]).replace(",", "").replace("£", "").replace("$", "").strip())
        except InvalidOperation:
            pass

    record = NormalizedRecord(
        tenant=tenant,
        raw_record=raw,
        scope=Scope.SCOPE_2,
        category=EmissionCategory.ELECTRICITY,
        period_start=period_start,
        period_end=period_end,
        invoice_date=invoice_date,
        country=country,
        location_raw=row.get("site", ""),
        original_quantity=qty,
        original_unit=raw_unit,
        original_cost=cost,
        quantity_kwh=quantity_kwh,
        meter_id=row.get("meter_id", ""),
        tariff_code=row.get("tariff", ""),
        is_estimated_read=is_estimated,
        emission_factor=factor,
        co2e_tonnes=co2e,
        status=RecordStatus.PENDING,
    )
    return record, flags, errors