"""URL patterns for site plugins. Imported lazily via ``include('ui.plugins.urls')``."""

from ui import plugins

urlpatterns = plugins.urlpatterns()
