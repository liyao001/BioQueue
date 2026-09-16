from django.urls import reverse

from QueueDB.models import ProtocolList, ProtocolShortcut, Step
from ui3.services import compute_step_hash, protocol_steps
from ui3.tests import Ui3TestCase


class ProtocolTests(Ui3TestCase):
    def test_list_hides_other_users_protocols(self):
        self.login()
        response = self.client.get(reverse("ui3:protocols"))
        self.assertContains(response, "RNA-seq")
        self.assertNotContains(response, "secret-proto")
        self.assertContains(response, "page-head")

    def test_create_protocol_with_steps(self):
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_create"),
            {
                "name": "ATAC",
                "description": "peaks",
                "software": ["bwa", "macs2"],
                "parameter": ["mem {InputFile}", "-t bam"],
                "env": ["", ""],
            },
        )
        self.assertEqual(response.status_code, 302)
        proto = ProtocolList.objects.get(name="ATAC")
        steps = list(protocol_steps(proto))
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].software, "bwa")
        self.assertEqual(steps[0].hash, compute_step_hash("bwa", "mem {InputFile}"))
        self.assertIn("select={}".format(proto.id), response["Location"])

    def test_add_and_reorder_steps(self):
        self.login()
        Step.objects.create(
            parent=self.protocol,
            software="first",
            parameter="a",
            step_order=1,
            hash=compute_step_hash("first", "a"),
            user=self.user,
        )
        self.client.post(
            reverse("ui3:step_create", args=[self.protocol.id]),
            {"software": "second", "parameter": "b"},
        )
        steps = list(protocol_steps(self.protocol))
        self.assertEqual([s.software for s in steps], ["first", "second"])
        second = steps[1]
        self.client.post(reverse("ui3:step_move", args=[second.id]), {"direction": "up"})
        steps = list(protocol_steps(self.protocol))
        self.assertEqual([s.software for s in steps], ["second", "first"])

    def test_clone_protocol(self):
        Step.objects.create(
            parent=self.protocol,
            software="cutadapt",
            parameter="-q 20",
            step_order=1,
            hash=compute_step_hash("cutadapt", "-q 20"),
            user=self.user,
        )
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_clone", args=[self.protocol.id]),
            {"name": "RNA-seq copy", "copy_description": "1"},
        )
        self.assertEqual(response.status_code, 302)
        dest = ProtocolList.objects.get(name="RNA-seq copy")
        self.assertEqual(dest.description, "demo")
        self.assertEqual(protocol_steps(dest).count(), 1)
        self.assertEqual(protocol_steps(dest).first().software, "cutadapt")

    def test_delete_protocol(self):
        self.login()
        pk = self.protocol.id
        response = self.client.post(reverse("ui3:protocol_delete", args=[pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProtocolList.objects.filter(pk=pk).exists())

    def test_cannot_edit_foreign_protocol(self):
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_update", args=[self.other_protocol.id]),
            {"name": "hacked"},
        )
        self.assertEqual(response.status_code, 403)

    def test_cannot_mutate_public_protocol(self):
        public = ProtocolList.objects.create(name="shared-public", user=None, ver="pub1")
        self.login()
        listed = self.client.get(reverse("ui3:protocols"))
        self.assertContains(listed, "shared-public")
        self.assertNotContains(listed, "Delete protocol 'shared-public'")
        detail = self.client.get(reverse("ui3:protocol_detail", args=[public.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Clone it to make your own")
        update = self.client.post(
            reverse("ui3:protocol_update", args=[public.id]),
            {"name": "hacked-public"},
        )
        self.assertEqual(update.status_code, 403)
        public.refresh_from_db()
        self.assertEqual(public.name, "shared-public")
        delete = self.client.post(reverse("ui3:protocol_delete", args=[public.id]))
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(ProtocolList.objects.filter(pk=public.id).exists())
        step = self.client.post(
            reverse("ui3:step_create", args=[public.id]),
            {"software": "evil", "parameter": "x"},
        )
        self.assertEqual(step.status_code, 403)

    def test_can_clone_public_protocol(self):
        public = ProtocolList.objects.create(name="public-src", description="ok", user=None, ver="pub2")
        Step.objects.create(
            parent=public,
            software="echo",
            parameter="hi",
            step_order=1,
            hash=compute_step_hash("echo", "hi"),
        )
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_clone", args=[public.id]),
            {"name": "my-copy", "copy_description": "1"},
        )
        self.assertEqual(response.status_code, 302)
        dest = ProtocolList.objects.get(name="my-copy")
        self.assertEqual(dest.user, self.user)
        self.assertEqual(protocol_steps(dest).count(), 1)

    def test_shortcut_crud_and_clone_copy(self):
        self.login()
        create = self.client.post(
            reverse("ui3:shortcut_create", args=[self.protocol.id]),
            {
                "label": "Evaluate",
                "href_template": "/ui/eval/{id}",
                "params_template": "?x=1",
                "order": "2",
                "active": "1",
            },
        )
        self.assertEqual(create.status_code, 302)
        sc = ProtocolShortcut.objects.get(protocol=self.protocol, label="Evaluate")
        self.assertEqual(sc.user, self.user)
        self.assertEqual(sc.href_template, "/ui/eval/{id}")
        listed = self.client.get(reverse("ui3:protocol_detail", args=[self.protocol.id]))
        self.assertContains(listed, "Evaluate")
        self.assertContains(listed, "/ui/eval/{id}")
        toggle = self.client.post(reverse("ui3:shortcut_toggle", args=[sc.id]))
        self.assertIn(toggle.status_code, (200, 302))
        sc.refresh_from_db()
        self.assertEqual(sc.active, 0)
        edit = self.client.post(
            reverse("ui3:shortcut_edit", args=[sc.id]),
            {
                "label": "Eval2",
                "href_template": "/ui/eval2/{id}",
                "params_template": "",
                "order": "1",
                "active": "1",
            },
        )
        self.assertIn(edit.status_code, (200, 302))
        sc.refresh_from_db()
        self.assertEqual(sc.label, "Eval2")
        clone = self.client.post(
            reverse("ui3:protocol_clone", args=[self.protocol.id]),
            {"name": "with-sc", "copy_description": "1", "copy_shortcuts": "1"},
        )
        self.assertEqual(clone.status_code, 302)
        dest = ProtocolList.objects.get(name="with-sc")
        copied = ProtocolShortcut.objects.filter(protocol=dest, label="Eval2")
        self.assertEqual(copied.count(), 1)
        delete = self.client.post(reverse("ui3:shortcut_delete", args=[sc.id]))
        self.assertIn(delete.status_code, (200, 302))
        self.assertFalse(ProtocolShortcut.objects.filter(pk=sc.id).exists())

    def test_cannot_edit_foreign_shortcut(self):
        sc = ProtocolShortcut.objects.create(
            user=self.other,
            protocol=self.other_protocol,
            label="secret",
            href_template="/x/{id}",
        )
        self.login()
        response = self.client.post(reverse("ui3:shortcut_delete", args=[sc.id]))
        self.assertEqual(response.status_code, 403)

    def test_htmx_detail_partial(self):
        self.login()
        response = self.client.get(
            reverse("ui3:protocol_detail", args=[self.protocol.id]),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="protocol-detail",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RNA-seq")
        self.assertContains(response, "ui-combo")
        self.assertContains(response, reverse("ui3:environment_options"))
        self.assertNotContains(response, "<html")

    def test_search_preserves_selected_protocol(self):
        self.login()
        response = self.client.get(reverse("ui3:protocols"), {"q": "RNA", "select": str(self.protocol.id)})
        self.assertContains(response, 'name="select"')
        self.assertContains(response, 'value="{}"'.format(self.protocol.id))
        self.assertContains(response, "page size")
        self.assertContains(response, "protocol")
        self.assertContains(response, "Oldest")

    def test_environment_options_filter(self):
        from QueueDB.models import VirtualEnvironment

        VirtualEnvironment.objects.create(name="py310", ve_type="conda", value="x", user=self.user)
        VirtualEnvironment.objects.create(name="tools", ve_type="venv", value="y", user=self.user)
        self.login()
        hit = self.client.get(reverse("ui3:environment_options"), {"combo_q": "py3"})
        self.assertEqual(hit.status_code, 200)
        self.assertContains(hit, "py310")
        self.assertContains(hit, "(conda)")
        self.assertNotContains(hit, "tools")
        by_type = self.client.get(reverse("ui3:environment_options"), {"q": "venv"})
        self.assertContains(by_type, "tools")
        self.assertNotContains(by_type, "py310")

    def test_create_shell_step_stores_multiline_script(self):
        self.login()
        script = 'echo "hello"\nls "{{Workspace}}"\n# comment\n'
        response = self.client.post(
            reverse("ui3:step_create", args=[self.protocol.id]),
            {"software": "__SHELL__", "parameter": script},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "step-shell-badge")
        self.assertContains(response, "Shell")
        step = protocol_steps(self.protocol).get()
        self.assertEqual(step.software, "__SHELL__")
        self.assertEqual(step.parameter, script)

    def test_create_protocol_with_shell_draft_step(self):
        self.login()
        script = "echo hi\ntrue"
        response = self.client.post(
            reverse("ui3:protocol_create"),
            {
                "name": "ShellPipe",
                "software": ["__SHELL__"],
                "parameter": [script],
                "env": [""],
            },
        )
        self.assertEqual(response.status_code, 302)
        proto = ProtocolList.objects.get(name="ShellPipe")
        steps = list(protocol_steps(proto))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].software, "__SHELL__")
        self.assertEqual(steps[0].parameter, script)

    def test_edit_shell_step_modal_opens_in_shell_mode(self):
        self.login()
        step = Step.objects.create(
            parent=self.protocol,
            software="__SHELL__",
            parameter="echo hi",
            step_order=1,
            hash=compute_step_hash("__SHELL__", "echo hi"),
            user=self.user,
        )
        response = self.client.get(
            reverse("ui3:step_edit", args=[step.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        html = response.content.decode()
        self.assertIn("data-ui3-step-kind", html)
        self.assertIn("__SHELL__", html)
        self.assertRegex(html, r'value="shell"[^>]*selected|selected[^>]*value="shell"')
        self.assertContains(response, "Script")
        self.assertNotContains(response, 'name="step_kind"')

    def test_htmx_edit_command_step_still_partial(self):
        self.login()
        step = Step.objects.create(
            parent=self.protocol,
            software="bwa",
            parameter="mem {InputFile}",
            step_order=1,
            hash=compute_step_hash("bwa", "mem {InputFile}"),
            user=self.user,
        )
        get = self.client.get(reverse("ui3:step_edit", args=[step.id]), HTTP_HX_REQUEST="true")
        self.assertEqual(get.status_code, 200)
        self.assertNotContains(get, "<html")
        self.assertContains(get, "bwa")
        self.assertRegex(get.content.decode(), r'value="command"[^>]*selected|selected[^>]*value="command"')
        post = self.client.post(
            reverse("ui3:step_edit", args=[step.id]),
            {"software": "bwa", "parameter": "mem -t 8"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(post.status_code, 200)
        self.assertNotContains(post, "<html")
        step.refresh_from_db()
        self.assertEqual(step.software, "bwa")
        self.assertEqual(step.parameter, "mem -t 8")

    def test_draft_step_row_kind_is_not_posted(self):
        self.login()
        response = self.client.get(reverse("ui3:protocol_step_row"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "data-ui3-step-kind")
        self.assertContains(response, 'name="software"')
        self.assertContains(response, 'name="parameter"')
        self.assertNotContains(response, 'name="step_kind"')

    def test_cannot_edit_foreign_shell_step(self):
        step = Step.objects.create(
            parent=self.other_protocol,
            software="__SHELL__",
            parameter="echo secret",
            step_order=1,
            hash=compute_step_hash("__SHELL__", "echo secret"),
            user=self.other,
        )
        self.login()
        get = self.client.get(reverse("ui3:step_edit", args=[step.id]), HTTP_HX_REQUEST="true")
        self.assertEqual(get.status_code, 403)
        post = self.client.post(
            reverse("ui3:step_edit", args=[step.id]),
            {"software": "hacked", "parameter": "x"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(post.status_code, 403)
        create = self.client.post(
            reverse("ui3:step_create", args=[self.other_protocol.id]),
            {"software": "__SHELL__", "parameter": "echo hi"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(create.status_code, 403)
        step.refresh_from_db()
        self.assertEqual(step.software, "__SHELL__")
        self.assertEqual(step.parameter, "echo secret")
        self.assertFalse(protocol_steps(self.other_protocol).filter(software="hacked").exists())
