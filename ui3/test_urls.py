from django.urls import include, path

urlpatterns = [
    path("ui3/", include("ui3.urls")),
]
