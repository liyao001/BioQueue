#!/usr/bin/env python
import os
import sys

sys.path.append(os.path.split(os.path.split(os.path.realpath(__file__))[0])[0])

from BioQueue.paths import django_settings_module

os.environ.setdefault("DJANGO_SETTINGS_MODULE", django_settings_module())

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
