from django.conf.urls import url
from . import views
import django.contrib.auth.views


urlpatterns = [
    url(r'^login/$', views.user_login, name='login'),
    url(r'^logout/$', django.contrib.auth.views.logout_then_login, name='logout'),
    url(r'^password-change/$', views.change_password, name='password_change'),
    url(r'^register/$', views.register, name='register'),
]
