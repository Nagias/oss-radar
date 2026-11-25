from django.urls import path

from features.browse import views

app_name = "browse"

urlpatterns = [
    path("", views.explore, name="explore"),
    path("repos/", views.repos, name="repos"),
    path("views/", views.views_page, name="views"),
    path("views/<int:view_id>/", views.view_edit, name="view_edit"),
    path("views/<int:view_id>/delete/", views.view_delete, name="view_delete"),
]
