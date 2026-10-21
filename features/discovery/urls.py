from django.urls import path

from features.discovery import views

app_name = "discovery"

urlpatterns = [
    path("", views.home, name="home"),
    path("scans/<int:scan_id>/", views.scan_detail, name="scan_detail"),
]
