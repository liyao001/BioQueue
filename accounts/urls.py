from django.urls import re_path
from . import views
import django.contrib.auth.views

app_name = "accounts"

urlpatterns = [
    re_path(r'^login/$', views.user_login, name='login'),
    re_path(r'^logout/$', django.contrib.auth.views.logout_then_login, name='logout'),
    re_path(r'^password-change/$', views.change_password, name='password_change'),
    re_path(r'^register/$', views.register, name='register'),
]
