from django.urls import path
from django.http import HttpResponse

urlpatterns = [
    path("", lambda request: HttpResponse("ok")),
]
