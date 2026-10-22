from django.urls import path

from features.rising import views

app_name = "rising"

urlpatterns = [
    path("", views.report, name="report"),
    path("watch/", views.watch, name="watch"),
    path("watch/<int:watch_id>/", views.watch_edit, name="watch_edit"),
    path("run/", views.run_now, name="run_now"),
    path("runs/<int:run_id>/stop/", views.stop, name="stop"),
]
