"""URL patterns for site plugins. Imported lazily via ``include('ui3.plugins.urls')``."""

from ui3 import plugins

urlpatterns = plugins.urlpatterns()
