from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Tenant, User, PlantSite, EmissionFactor,
    IngestionJob, RawRecord, NormalizedRecord, AuditLogEntry
)

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "created_at"]
    search_fields = ["name", "slug"]

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ["username", "email", "tenant", "is_analyst", "is_uploader"]
    list_filter  = ["tenant", "is_analyst", "is_uploader"]
    fieldsets = UserAdmin.fieldsets + (
        ("Breathe ESG", {"fields": ("tenant", "is_analyst", "is_uploader")}),
    )

@admin.register(PlantSite)
class PlantSiteAdmin(admin.ModelAdmin):
    list_display = ["sap_code", "name", "tenant", "country", "city"]
    search_fields = ["sap_code", "name"]
    list_filter  = ["tenant", "country"]

@admin.register(EmissionFactor)
class EmissionFactorAdmin(admin.ModelAdmin):
    list_display = ["category", "country", "fuel_type", "factor_value", "factor_unit", "valid_from", "valid_to", "source"]
    list_filter  = ["category", "country"]
    search_fields = ["category", "fuel_type", "source"]

@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display  = ["tenant", "source_type", "status", "total_rows", "parsed_rows", "failed_rows", "created_at"]
    list_filter   = ["tenant", "source_type", "status"]
    readonly_fields = ["created_at", "started_at", "finished_at", "file_hash"]

@admin.register(RawRecord)
class RawRecordAdmin(admin.ModelAdmin):
    list_display  = ["ingestion_job", "row_index", "normalized", "created_at"]
    list_filter   = ["normalized"]
    readonly_fields = ["raw_data", "created_at"]

@admin.register(NormalizedRecord)
class NormalizedRecordAdmin(admin.ModelAdmin):
    list_display  = ["tenant", "scope", "category", "period_start", "period_end", "co2e_tonnes", "status"]
    list_filter   = ["tenant", "scope", "category", "status"]
    search_fields = ["sap_document_number", "meter_id", "supplier_name"]
    readonly_fields = ["created_at", "updated_at", "raw_record"]

@admin.register(AuditLogEntry)
class AuditLogAdmin(admin.ModelAdmin):
    list_display  = ["record", "action", "field_name", "changed_by", "timestamp"]
    list_filter   = ["action"]
    readonly_fields = [f.name for f in AuditLogEntry._meta.get_fields()]