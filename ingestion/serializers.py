from rest_framework import serializers
from .models import (
    Tenant, IngestionJob, RawRecord,
    NormalizedRecord, AuditLogEntry, EmissionFactor
)


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Tenant
        fields = ["id", "name", "slug", "reporting_year_start", "reporting_year_end"]


class IngestionJobSerializer(serializers.ModelSerializer):
    success_rate = serializers.ReadOnlyField()
    created_by   = serializers.StringRelatedField()

    class Meta:
        model  = IngestionJob
        fields = [
            "id", "source_type", "status", "file_name",
            "total_rows", "parsed_rows", "failed_rows", "flagged_rows",
            "parse_errors", "success_rate", "created_by",
            "created_at", "started_at", "finished_at", "notes",
        ]
        read_only_fields = [
            "status", "total_rows", "parsed_rows",
            "failed_rows", "flagged_rows", "parse_errors",
            "created_at", "started_at", "finished_at",
        ]


class RawRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model  = RawRecord
        fields = ["id", "row_index", "raw_data", "normalized", "created_at"]


class NormalizedRecordSerializer(serializers.ModelSerializer):
    flags          = serializers.ListField(child=serializers.CharField())
    emission_factor = serializers.StringRelatedField()
    reviewed_by    = serializers.StringRelatedField()

    class Meta:
        model  = NormalizedRecord
        fields = [
            "id", "scope", "category", "status", "flags", "flag_notes",
            "period_start", "period_end", "invoice_date",
            "country", "location_raw", "plant_site",
            "original_quantity", "original_unit",
            "quantity_kwh", "quantity_kg", "quantity_km", "quantity_nights",
            "co2e_tonnes", "emission_factor",
            "fuel_type", "supplier_name",
            "meter_id", "tariff_code", "is_estimated_read",
            "travel_origin", "travel_destination", "travel_class",
            "vehicle_type", "traveller_count", "distance_method",
            "sap_document_number", "sap_material_code",
            "reviewed_by", "reviewed_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "scope", "category", "co2e_tonnes", "emission_factor",
            "reviewed_by", "reviewed_at", "created_at", "updated_at",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    changed_by = serializers.StringRelatedField()

    class Meta:
        model  = AuditLogEntry
        fields = [
            "id", "action", "field_name", "old_value",
            "new_value", "notes", "changed_by", "timestamp",
        ]


class EmissionFactorSerializer(serializers.ModelSerializer):
    class Meta:
        model  = EmissionFactor
        fields = [
            "id", "category", "country", "fuel_type",
            "factor_value", "factor_unit", "valid_from", "valid_to", "source",
        ]


# --- Upload serializers (for file ingestion endpoints) ---

class SAPUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    notes = serializers.CharField(required=False, allow_blank=True)


class UtilityUploadSerializer(serializers.Serializer):
    file  = serializers.FileField()
    notes = serializers.CharField(required=False, allow_blank=True)


class TravelUploadSerializer(serializers.Serializer):
    file  = serializers.FileField()
    notes = serializers.CharField(required=False, allow_blank=True)


# --- Review action serializers ---

class ApproveSerializer(serializers.Serializer):
    record_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of NormalizedRecord UUIDs to approve",
    )


class FlagSerializer(serializers.Serializer):
    record_ids = serializers.ListField(child=serializers.UUIDField())
    reason     = serializers.ChoiceField(choices=[
        "unit_ambiguous", "missing_factor", "outlier_value",
        "duplicate_suspected", "period_gap", "period_overlap",
        "plant_unknown", "negative_value", "manual_flag",
    ])
    note = serializers.CharField(required=False, allow_blank=True)