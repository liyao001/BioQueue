from django.urls import include, path, re_path
from django.views.generic import RedirectView

from ui3.http import redirect_ui3_prefix

urlpatterns = [
    path("", RedirectView.as_view(url="/ui/", permanent=False)),
    path("ui/", include("ui3.urls")),
    re_path(r"^ui3/(?P<rest>.*)$", redirect_ui3_prefix),
]
