from django.urls import path

from features.discovery import views

app_name = "discovery"

urlpatterns = [
    path("", views.home, name="home"),
    path("scans/<int:scan_id>/", views.scan_detail, name="scan_detail"),
    path("scans/<int:scan_id>/stop/", views.scan_stop, name="scan_stop"),
    path("scans/<int:scan_id>/resume/", views.scan_resume, name="scan_resume"),
]
