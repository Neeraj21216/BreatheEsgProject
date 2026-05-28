import hashlib
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from django.db.models import Count, Sum

from .models import (
    Tenant, IngestionJob, RawRecord, NormalizedRecord,
    AuditLogEntry, EmissionFactor, SourceType, RecordStatus
)
from .serializers import (
    TenantSerializer, IngestionJobSerializer, RawRecordSerializer,
    NormalizedRecordSerializer, AuditLogSerializer, EmissionFactorSerializer,
    SAPUploadSerializer, UtilityUploadSerializer, TravelUploadSerializer,
    ApproveSerializer, FlagSerializer,
)
from .parsers.sap import parse_sap_file
from .parsers.utility import parse_utility_file
from .parsers.travel import parse_travel_file


# ---------------------------------------------------------------------------
# Helper — get tenant from request (simplified: use first tenant for now)
# In production this comes from request.user.tenant
# ---------------------------------------------------------------------------

def get_tenant(request):
    return Tenant.objects.first()


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

from rest_framework.views import APIView

class DashboardStatsView(APIView):
    def get(self, request):
        tenant = get_tenant(request)
        if not tenant:
            return Response({"error": "No tenant configured"}, status=400)

        records = NormalizedRecord.objects.for_tenant(tenant)
        jobs    = IngestionJob.objects.for_tenant(tenant)

        stats = {
            "total_records":    records.count(),
            "pending":          records.filter(status=RecordStatus.PENDING).count(),
            "flagged":          records.filter(status=RecordStatus.FLAGGED).count(),
            "approved":         records.filter(status=RecordStatus.APPROVED).count(),
            "locked":           records.filter(status=RecordStatus.LOCKED).count(),
            "total_co2e":       records.aggregate(t=Sum("co2e_tonnes"))["t"] or 0,
            "by_scope": {
                "1": records.filter(scope="1").aggregate(t=Sum("co2e_tonnes"))["t"] or 0,
                "2": records.filter(scope="2").aggregate(t=Sum("co2e_tonnes"))["t"] or 0,
                "3": records.filter(scope="3").aggregate(t=Sum("co2e_tonnes"))["t"] or 0,
            },
            "total_jobs":       jobs.count(),
            "failed_jobs":      jobs.filter(status="failed").count(),
            "recent_jobs":      IngestionJobSerializer(
                                    jobs.order_by("-created_at")[:5], many=True
                                ).data,
        }
        return Response(stats)


# ---------------------------------------------------------------------------
# Ingestion Jobs
# ---------------------------------------------------------------------------

class IngestionJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IngestionJobSerializer

    def get_queryset(self):
        tenant = get_tenant(self.request)
        return IngestionJob.objects.for_tenant(tenant).order_by("-created_at")

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload_sap(self, request):
        return self._handle_upload(request, SAPUploadSerializer, SourceType.SAP_FLAT_FILE, parse_sap_file)

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload_utility(self, request):
        return self._handle_upload(request, UtilityUploadSerializer, SourceType.UTILITY_CSV, parse_utility_file)

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload_travel(self, request):
        return self._handle_upload(request, TravelUploadSerializer, SourceType.TRAVEL_CSV, parse_travel_file)

    def _handle_upload(self, request, upload_serializer_class, source_type, parser_fn):
        ser = upload_serializer_class(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=400)

        tenant = get_tenant(request)
        file   = request.FILES["file"]

        # Compute file hash to detect duplicate uploads
        content  = file.read()
        sha256   = hashlib.sha256(content).hexdigest()
        file.seek(0)

        job = IngestionJob.objects.create(
            tenant      = tenant,
            source_type = source_type,
            status      = "processing",
            file_name   = file.name,
            file_hash   = sha256,
            file_size   = file.size,
            notes       = ser.validated_data.get("notes", ""),
            started_at  = timezone.now(),
            created_by  = request.user if request.user.is_authenticated else None,
        )

        try:
            result = parser_fn(file, job, tenant)
            job.status      = "complete" if result["failed"] == 0 else "partial"
            job.total_rows  = result["total"]
            job.parsed_rows = result["parsed"]
            job.failed_rows = result["failed"]
            job.flagged_rows = result["flagged"]
            job.parse_errors = result["errors"]
        except Exception as e:
            job.status = "failed"
            job.parse_errors = [{"error": str(e)}]
        finally:
            job.finished_at = timezone.now()
            job.save()

        return Response(IngestionJobSerializer(job).data, status=201)


# ---------------------------------------------------------------------------
# Normalized Records + review actions
# ---------------------------------------------------------------------------

class NormalizedRecordViewSet(viewsets.ModelViewSet):
    serializer_class = NormalizedRecordSerializer

    def get_queryset(self):
        tenant = get_tenant(self.request)
        qs = NormalizedRecord.objects.for_tenant(tenant).select_related(
            "plant_site", "emission_factor", "reviewed_by"
        )
        # Filters from query params
        if scope := self.request.query_params.get("scope"):
            qs = qs.filter(scope=scope)
        if category := self.request.query_params.get("category"):
            qs = qs.filter(category=category)
        if status := self.request.query_params.get("status"):
            qs = qs.filter(status=status)
        if job_id := self.request.query_params.get("job"):
            qs = qs.filter(raw_record__ingestion_job_id=job_id)
        return qs.order_by("-period_start")

    @action(detail=False, methods=["post"])
    def approve(self, request):
        ser = ApproveSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=400)

        tenant  = get_tenant(request)
        updated = 0
        errors  = []

        for rid in ser.validated_data["record_ids"]:
            try:
                rec = NormalizedRecord.objects.for_tenant(tenant).get(id=rid)
                rec.approve(request.user if request.user.is_authenticated else None)
                updated += 1
            except NormalizedRecord.DoesNotExist:
                errors.append(str(rid))
            except ValueError as e:
                errors.append(f"{rid}: {e}")

        return Response({"approved": updated, "errors": errors})

    @action(detail=False, methods=["post"])
    def flag(self, request):
        ser = FlagSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=400)

        tenant  = get_tenant(request)
        updated = 0
        errors  = []
        user    = request.user if request.user.is_authenticated else None

        for rid in ser.validated_data["record_ids"]:
            try:
                rec = NormalizedRecord.objects.for_tenant(tenant).get(id=rid)
                rec.flag(
                    reason=ser.validated_data["reason"],
                    note=ser.validated_data.get("note", ""),
                    user=user,
                )
                updated += 1
            except NormalizedRecord.DoesNotExist:
                errors.append(str(rid))
            except ValueError as e:
                errors.append(f"{rid}: {e}")

        return Response({"flagged": updated, "errors": errors})

    @action(detail=True, methods=["get"])
    def audit_log(self, request, pk=None):
        tenant = get_tenant(request)
        record = NormalizedRecord.objects.for_tenant(tenant).get(pk=pk)
        log    = AuditLogEntry.objects.filter(record=record).order_by("timestamp")
        return Response(AuditLogSerializer(log, many=True).data)


# ---------------------------------------------------------------------------
# Raw Records (read-only — source of truth, never edited)
# ---------------------------------------------------------------------------

class RawRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RawRecordSerializer

    def get_queryset(self):
        tenant = get_tenant(self.request)
        return RawRecord.objects.for_tenant(tenant).order_by("ingestion_job", "row_index")


# ---------------------------------------------------------------------------
# Emission Factors
# ---------------------------------------------------------------------------

class EmissionFactorViewSet(viewsets.ModelViewSet):
    serializer_class   = EmissionFactorSerializer
    queryset           = EmissionFactor.objects.all().order_by("category", "country")