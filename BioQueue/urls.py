"""BioQueue URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from ui.http import redirect_ui3_prefix
from ui.plugins.api_urls import urlpatterns as api_urlpatterns

urlpatterns = [
    path("", RedirectView.as_view(url="/ui/", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("ui/", include("ui.urls")),
    re_path(r"^ui3/(?P<rest>.*)$", redirect_ui3_prefix),
]
if api_urlpatterns:
    urlpatterns.append(path("api/", include(api_urlpatterns)))
