from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DashboardStatsView,
    IngestionJobViewSet,
    NormalizedRecordViewSet,
    RawRecordViewSet,
    EmissionFactorViewSet,
)

router = DefaultRouter()
router.register("jobs",    IngestionJobViewSet,    basename="jobs")
router.register("records", NormalizedRecordViewSet, basename="records")
router.register("raw",     RawRecordViewSet,        basename="raw")
router.register("factors", EmissionFactorViewSet,   basename="factors")

urlpatterns = [
    path("dashboard/", DashboardStatsView.as_view(), name="dashboard"),
    path("", include(router.urls)),
]