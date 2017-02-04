#!/usr/bin/env python
import os
import sys
from django.core.wsgi import get_wsgi_application

sys.path.append(os.path.split(os.path.split(os.path.realpath(__file__))[0])[0])
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "BioQueue.settings")

application = get_wsgi_application()
