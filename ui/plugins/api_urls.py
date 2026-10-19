"""Optional ``/api/`` routes.

Lab installs can provide ``ui.views.plugins.urls.api_urlpatterns``. A stock
install has no such module, so ``/api/`` is left unmounted. These patterns stay
off the ``/ui/`` plugin table: the legacy plugin remounts that table, and the
lab API entry points are rooted at ``/api/``.
"""
import logging

logger = logging.getLogger(__name__)


def load_api_urlpatterns():
    try:
        from ui.views.plugins.urls import api_urlpatterns as patterns
    except ImportError:
        logger.debug("ui.views.plugins is not installed", exc_info=True)
        return []
    except Exception:
        logger.exception("lab /api/ routes failed to load")
        return []
    return list(patterns or [])


urlpatterns = load_api_urlpatterns()
