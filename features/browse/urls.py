from django.urls import path

from features.browse import views

app_name = "browse"

urlpatterns = [
    path("", views.repos, name="repos"),
]
