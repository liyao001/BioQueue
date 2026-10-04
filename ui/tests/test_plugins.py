from django.http import HttpResponse
from django.urls import path, reverse
from QueueDB.models import ProtocolShortcut

from ui.plugins import Plugin
from ui.tests import Ui3TestCase


class _ProbePlugin(Plugin):
    name = "probe"

    def urlpatterns(self):
        return [path("probe/", lambda request: HttpResponse("probe-ok"), name="plugin_probe")]

    def nav_items(self, request):
        return [{"href": "/ui/probe/", "label": "ProbeNav", "icon": "fa-solid fa-puzzle-piece"}]

    def shortcut_presets(self):
        return [{
            "label": "Evaluate",
            "href_template": "/ui/probe/{id}",
        }]


class _BoomPlugin(Plugin):
    name = "boom"

    def shortcut_presets(self):
        raise RuntimeError("boom")

    def nav_items(self, request):
        raise RuntimeError("boom")

    def urlpatterns(self):
        raise RuntimeError("boom")


class PluginTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        from ui import plugins

        self._plugins = plugins
        self._saved = list(plugins.get_plugins())
        plugins.reset()
        plugins._loaded = True

    def tearDown(self):
        self._plugins.reset()
        self._plugins._loaded = True
        for plugin in self._saved:
            self._plugins.register(plugin)
        super().tearDown()

    def test_job_card_does_not_show_plugin_without_shortcut(self):
        self._plugins.register(_ProbePlugin())
        self.make_job()
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertNotContains(response, "Evaluate")
        self.assertNotContains(response, 'title="Shortcuts"')
        self.assertContains(response, "ProbeNav")

    def test_protocol_page_lists_presets_and_creates_shortcut(self):
        self._plugins.register(_ProbePlugin())
        self.login()
        page = self.client.get(reverse("ui3:protocol_detail", args=[self.protocol.id]))
        self.assertContains(page, "From plugins")
        self.assertContains(page, "/ui/probe/{id}")
        created = self.client.post(
            reverse("ui3:shortcut_create", args=[self.protocol.id]),
            {"label": "Evaluate", "href_template": "/ui/probe/{id}", "active": "1"},
        )
        self.assertIn(created.status_code, (200, 302))
        sc = ProtocolShortcut.objects.get(protocol=self.protocol, label="Evaluate")
        self.assertEqual(sc.href_template, "/ui/probe/{id}")
        job = self.make_job()
        jobs = self.client.get(reverse("ui3:jobs"))
        self.assertContains(jobs, "Evaluate")
        self.assertContains(jobs, "/ui/probe/{}".format(job.id))

    def test_broken_plugin_does_not_break_protocol_page(self):
        self._plugins.register(_BoomPlugin())
        self.login()
        response = self.client.get(reverse("ui3:protocol_detail", args=[self.protocol.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "From plugins")

    def test_duplicate_name_is_ignored(self):
        self._plugins.register(_ProbePlugin())
        self._plugins.register(_ProbePlugin())
        self.assertEqual(len(self._plugins.get_plugins()), 1)

    def test_urlpatterns_are_collected(self):
        self._plugins.register(_ProbePlugin())
        names = [getattr(p, "name", None) for p in self._plugins.urlpatterns()]
        self.assertIn("plugin_probe", names)

    def test_broken_urlpatterns_are_skipped(self):
        self._plugins.register(_BoomPlugin())
        self.assertEqual(self._plugins.urlpatterns(), [])
