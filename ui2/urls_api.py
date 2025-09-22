#!/usr/bin/env python
# -*- coding: utf-8 -*-

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .api import (
    JobViewSet,
    ProtocolListViewSet,
    StepViewSet,
    ReferenceViewSet,
    WorkspaceViewSet,
    SampleViewSet,
    TrainingViewSet,
    PredictionViewSet,
    VirtualEnvironmentViewSet,
    LoginView,
    LogoutView,
    MeView,
    ProtocolShortcutViewSet,
)

router = DefaultRouter()
router.register(r"jobs", JobViewSet)
router.register(r"protocols", ProtocolListViewSet, basename="protocol")
router.register(r"steps", StepViewSet)
router.register(r"references", ReferenceViewSet)
router.register(r"workspaces", WorkspaceViewSet)
router.register(r"samples", SampleViewSet)
router.register(r"trainings", TrainingViewSet)
router.register(r"predictions", PredictionViewSet)
router.register(r"virtual-environments", VirtualEnvironmentViewSet)
router.register(r"shortcuts", ProtocolShortcutViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("auth/login/", LoginView.as_view(), name="ui2_login"),
    path("auth/logout/", LogoutView.as_view(), name="ui2_logout"),
    path("auth/me/", MeView.as_view(), name="ui2_me"),
]


