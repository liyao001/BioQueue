"""Load the old ``ui.views.plugins`` URL table onto /ui/.

Dec / WandB views stay in that package (lab-specific, not in git). This wrapper
only remounts them so protocol shortcuts keep working after ui3 took ``/ui/``.
"""

import logging

from ui3.plugins import Plugin, register

logger = logging.getLogger(__name__)


class LegacyUiPlugins(Plugin):
    name = "legacy-ui"

    def urlpatterns(self):
        try:
            from ui.views.plugins.urls import urlpatterns as urls
        except Exception:
            logger.debug("ui.views.plugins is not installed", exc_info=True)
            return []
        return list(urls or [])


register(LegacyUiPlugins())
