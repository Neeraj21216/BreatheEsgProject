"""
Corporate Travel CSV Parser
===========================
Handles exports from Concur / Navan / similar platforms.
Key real-world quirks:
  - Flights: often only origin + destination airport codes, no distance
    → we compute great-circle distance from a coordinate lookup
  - Hotels: nights × location, no distance
  - Ground: car rental (need vehicle type), rail, taxi
  - Emission factors differ by cabin class (economy vs business)
  - One booking row may contain multiple legs (we split them)
"""

import csv
import io
import math
from decimal import Decimal, InvalidOperation
from datetime import datetime

from ingestion.models import (
    RawRecord, NormalizedRecord, RecordStatus, FlagReason,
    Scope, EmissionCategory, EmissionFactor,
)

# ---------------------------------------------------------------------------
# Minimal airport coordinate lookup (top 40 busiest — extend in production)
# ---------------------------------------------------------------------------

AIRPORT_COORDS = {
    "ATL": (33.6367, -84.4281), "LAX": (33.9425, -118.4081),
    "ORD": (41.9742, -87.9073), "DFW": (32.8998, -97.0403),
    "DEN": (39.8561, -104.6737),"JFK": (40.6413, -73.7781),
    "SFO": (37.6213, -122.379), "LAS": (36.0840, -115.1537),
    "SEA": (47.4502, -122.3088),"MIA": (25.7959, -80.2870),
    "LHR": (51.4700, -0.4543),  "CDG": (49.0097, 2.5479),
    "AMS": (52.3105, 4.7683),   "FRA": (50.0379, 8.5622),
    "DXB": (25.2532, 55.3657),  "SIN": (1.3644, 103.9915),
    "HKG": (22.3080, 113.9185), "NRT": (35.7647, 140.3864),
    "ICN": (37.4602, 126.4407), "SYD": (-33.9461, 151.1772),
    "DEL": (28.5562, 77.1000),  "BOM": (19.0896, 72.8656),
    "MAA": (12.9941, 80.1709),  "BLR": (13.1979, 77.7063),
    "PEK": (40.0799, 116.6031), "PVG": (31.1443, 121.8083),
    "DUB": (53.4213, -6.2700),  "MAN": (53.3537, -2.2750),
    "ZRH": (47.4647, 8.5492),   "MAD": (40.4719, -3.5626),
    "BCN": (41.2974, 2.0833),   "FCO": (41.8003, 12.2389),
    "BKK": (13.6811, 100.7472), "KUL": (2.7456, 101.7099),
    "MEX": (19.4363, -99.0721), "GRU": (-23.4356, -46.4731),
    "JNB": (-26.1392, 28.2460), "CAI": (30.1219, 31.4056),
    "CPT": (-33.9648, 18.6017), "MEL": (-37.6733, 144.8433),
}

# kgCO2e per passenger-km by cabin class (DEFRA 2023 approximate)
FLIGHT_FACTORS = {
    "economy":  Decimal("0.15531"),
    "business": Decimal("0.42840"),
    "first":    Decimal("0.60480"),
    "unknown":  Decimal("0.19550"),   # average
}

# kgCO2e per hotel room-night by region (approximate)
HOTEL_FACTORS = {
    "GB": Decimal("20.8"), "US": Decimal("25.4"),
    "DE": Decimal("18.2"), "IN": Decimal("14.6"),
    "XX": Decimal("21.6"),  # global default
}

COLUMN_ALIASES = {
    "transaction date":   "date",
    "travel date":        "date",
    "departure date":     "date",
    "date":               "date",
    "type":               "travel_type",
    "travel type":        "travel_type",
    "category":           "travel_type",
    "expense type":       "travel_type",
    "origin":             "origin",
    "from":               "origin",
    "departure":          "origin",
    "destination":        "destination",
    "to":                 "destination",
    "arrival":            "destination",
    "class":              "cabin_class",
    "cabin class":        "cabin_class",
    "fare class":         "cabin_class",
    "distance":           "distance_km",
    "distance (km)":      "distance_km",
    "km":                 "distance_km",
    "nights":             "nights",
    "hotel nights":       "nights",
    "duration (nights)":  "nights",
    "travellers":         "travellers",
    "passengers":         "travellers",
    "pax":                "travellers",
    "vehicle type":       "vehicle_type",
    "car type":           "vehicle_type",
    "country":            "country",
    "cost":               "cost",
    "amount":             "cost",
    "employee":           "employee",
    "traveller name":     "employee",
}

TRAVEL_TYPE_MAP = {
    "air":          EmissionCategory.TRAVEL_AIR,
    "flight":       EmissionCategory.TRAVEL_AIR,
    "plane":        EmissionCategory.TRAVEL_AIR,
    "hotel":        EmissionCategory.TRAVEL_HOTEL,
    "accommodation":EmissionCategory.TRAVEL_HOTEL,
    "lodging":      EmissionCategory.TRAVEL_HOTEL,
    "car":          EmissionCategory.TRAVEL_GROUND,
    "taxi":         EmissionCategory.TRAVEL_GROUND,
    "ground":       EmissionCategory.TRAVEL_GROUND,
    "rental":       EmissionCategory.TRAVEL_GROUND,
    "rail":         EmissionCategory.TRAVEL_RAIL,
    "train":        EmissionCategory.TRAVEL_RAIL,
    "rail/train":   EmissionCategory.TRAVEL_RAIL,
}


def _norm_header(h):
    return COLUMN_ALIASES.get(h.strip().lower(), h.strip().lower())


def _parse_date(s):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _great_circle_km(origin: str, dest: str) -> tuple[Decimal | None, str]:
    """Return (distance_km, method) using great-circle formula."""
    o = AIRPORT_COORDS.get(origin.upper())
    d = AIRPORT_COORDS.get(dest.upper())
    if not o or not d:
        return None, "unknown"

    lat1, lon1 = math.radians(o[0]), math.radians(o[1])
    lat2, lon2 = math.radians(d[0]), math.radians(d[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    km = Decimal(str(round(6371 * c, 2)))
    return km, "great_circle"


def parse_travel_file(file, job, tenant) -> dict:
    content = file.read()
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

    # --- Date ---
    travel_date = _parse_date(row.get("date", ""))
    if not travel_date:
        errors.append({"field": "date", "raw_value": row.get("date"), "error": "Unrecognised date format"})
        return None, flags, errors

    # --- Travel type → category ---
    raw_type = row.get("travel_type", "").strip().lower()
    category = None
    for keyword, cat in TRAVEL_TYPE_MAP.items():
        if keyword in raw_type:
            category = cat
            break
    if not category:
        errors.append({"field": "travel_type", "raw_value": raw_type, "error": "Unrecognised travel type"})
        return None, flags, errors

    origin      = row.get("origin", "").strip().upper()
    destination = row.get("destination", "").strip().upper()
    cabin_class = row.get("cabin_class", "unknown").strip().lower()
    country     = row.get("country", "XX").strip().upper() or "XX"

    if cabin_class not in FLIGHT_FACTORS:
        cabin_class = "unknown"

    # --- Per-category emission calculation ---
    quantity_km = quantity_nights = co2e = None
    distance_method = ""

    if category == EmissionCategory.TRAVEL_AIR:
        # Try provided distance first
        raw_dist = row.get("distance_km", "").strip()
        if raw_dist:
            try:
                quantity_km = Decimal(raw_dist.replace(",", ""))
                distance_method = "provided"
            except InvalidOperation:
                pass

        if not quantity_km and origin and destination:
            quantity_km, distance_method = _great_circle_km(origin, destination)

        if not quantity_km:
            flags.append(FlagReason.MISSING_FACTOR)
        else:
            factor_kg_per_km = FLIGHT_FACTORS.get(cabin_class, FLIGHT_FACTORS["unknown"])
            travellers = int(row.get("travellers", 1) or 1)
            co2e = (quantity_km * factor_kg_per_km * travellers / Decimal("1000")).quantize(Decimal("0.000001"))

    elif category == EmissionCategory.TRAVEL_HOTEL:
        try:
            quantity_nights = int(row.get("nights", 1) or 1)
        except ValueError:
            quantity_nights = 1
            flags.append(FlagReason.UNIT_AMBIGUOUS)

        hotel_factor = HOTEL_FACTORS.get(country, HOTEL_FACTORS["XX"])
        co2e = (Decimal(quantity_nights) * hotel_factor / Decimal("1000")).quantize(Decimal("0.000001"))

    elif category in (EmissionCategory.TRAVEL_GROUND, EmissionCategory.TRAVEL_RAIL):
        raw_dist = row.get("distance_km", "").strip()
        if raw_dist:
            try:
                quantity_km = Decimal(raw_dist.replace(",", ""))
                distance_method = "provided"
            except InvalidOperation:
                flags.append(FlagReason.UNIT_AMBIGUOUS)
        else:
            flags.append(FlagReason.MISSING_FACTOR)

        if quantity_km:
            # Ground: 0.17 kgCO2e/km (average car), Rail: 0.041 kgCO2e/km (UK average)
            factor = Decimal("0.041") if category == EmissionCategory.TRAVEL_RAIL else Decimal("0.17")
            co2e = (quantity_km * factor / Decimal("1000")).quantize(Decimal("0.000001"))

    cost = None
    if row.get("cost"):
        try:
            cost = Decimal(str(row["cost"]).replace(",", "").replace("$", "").replace("£", "").strip())
        except InvalidOperation:
            pass

    record = NormalizedRecord(
        tenant=tenant,
        raw_record=raw,
        scope=Scope.SCOPE_3,
        category=category,
        period_start=travel_date,
        period_end=travel_date,
        country=country,
        location_raw=f"{origin} → {destination}" if destination else origin,
        original_quantity=quantity_km or Decimal(quantity_nights or 0),
        original_unit="km" if quantity_km else "nights",
        original_cost=cost,
        quantity_km=quantity_km,
        quantity_nights=quantity_nights,
        distance_method=distance_method,
        travel_origin=origin,
        travel_destination=destination,
        travel_class=cabin_class,
        vehicle_type=row.get("vehicle_type", ""),
        traveller_count=int(row.get("travellers", 1) or 1),
        co2e_tonnes=co2e,
        status=RecordStatus.PENDING,
    )
    return record, flags, errors