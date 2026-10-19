"""
WSGI config for BioQueue project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import os

from BioQueue.paths import django_settings_module

os.environ.setdefault("DJANGO_SETTINGS_MODULE", django_settings_module())

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
