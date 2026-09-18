"""BioQueue URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from ui3.http import redirect_ui3_prefix

urlpatterns = [
    path("", RedirectView.as_view(url="/ui/", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("ui/", include("ui3.urls")),
    re_path(r"^ui3/(?P<rest>.*)$", redirect_ui3_prefix),
]
