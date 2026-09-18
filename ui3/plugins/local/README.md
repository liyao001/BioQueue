# Local ui3 plugins

Files in this directory (except this README and `__init__.py`) are gitignored.
Use this for lab-specific BioQueue views (the old `ui/views/plugins/` WandB / Dec
pattern) without putting them in the general repo.

Job cards do not call plugins directly. Add a protocol shortcut whose href
points at `/ui/…/{id}`. Plugins can advertise those hrefs as presets on
the protocol page.

## Drop-in module

```python
# ui3/plugins/local/example.py
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path

from QueueDB.models import Job
from ui3.plugins import Plugin, register


def ping(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    return HttpResponse("job {}".format(job.id))


class ExamplePlugin(Plugin):
    name = "example"

    def urlpatterns(self):
        return [path("example/<int:job_id>/", ping, name="example_ping")]

    def shortcut_presets(self):
        return [{
            "label": "Example",
            "href_template": "/ui/example/{id}/",
        }]


register(ExamplePlugin())
```

Restart Django after adding a module. Then on the protocol page, click the
**Example** preset (or type the href by hand). Jobs of that protocol get the
shortcut on the card ellipsis.

Optional: `nav_items(request)` for a rare top-level page. Do not use it for
per-job Dec/WandB actions.

## Alternative: settings

In `BioQueue/settings.py`:

```python
UI3_PLUGINS = ["my_lab.ui3_plugins.wandb"]
```

That module should call `register(...)` at import time, same as a local file.
