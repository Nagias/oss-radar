from django.urls import path

from features.browse import views

app_name = "browse"

urlpatterns = [
    path("", views.explore, name="explore"),
    path("repos/", views.repos, name="repos"),
]
