from django.urls import reverse

from QueueDB.models import ProtocolList, ProtocolShortcut, Reference, Step, VirtualEnvironment
from ui.services import compute_step_hash, protocol_steps
from ui.tests import Ui3TestCase


class ProtocolTests(Ui3TestCase):
    def test_list_hides_other_users_protocols(self):
        self.login()
        response = self.client.get(reverse("ui3:protocols"))
        self.assertContains(response, "RNA-seq")
        self.assertNotContains(response, "secret-proto")
        self.assertContains(response, "page-head")
        self.assertContains(response, "Import JSON")
        self.assertContains(response, reverse("ui3:protocol_import"))
        self.assertContains(response, reverse("ui3:protocol_template_create"))
        self.assertContains(response, "New Template")
        self.assertContains(response, "protocol-list-toggle")
        self.assertContains(response, "Collapse list")
        self.assertContains(response, "Expand list")
        self.assertContains(response, 'id="protocol-list-body"')

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

    def test_drag_reorder_steps(self):
        self.login()
        created = []
        for index, name in enumerate(("alpha", "beta", "gamma"), start=1):
            created.append(Step.objects.create(
                parent=self.protocol,
                software=name,
                parameter="p",
                step_order=index,
                hash=compute_step_hash(name, "p"),
                user=self.user,
            ))
        page = self.client.get(reverse("ui3:protocol_detail", args=[self.protocol.id]))
        self.protocol.refresh_from_db()
        self.assertContains(page, "step-drag")
        self.assertContains(page, "Version")
        self.assertContains(page, self.protocol.ver)
        self.assertNotContains(page, 'name="ver"')
        self.assertContains(page, "step-table")
        self.assertContains(page, reverse("ui3:step_reorder", args=[self.protocol.id]))
        self.assertContains(page, "stepDragStart")
        self.assertContains(page, 'swap: "innerHTML"')
        order = "{},{},{}".format(created[2].id, created[0].id, created[1].id)
        response = self.client.post(
            reverse("ui3:step_reorder", args=[self.protocol.id]),
            {"order": order},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        steps = list(protocol_steps(self.protocol))
        self.assertEqual([s.software for s in steps], ["gamma", "alpha", "beta"])
        self.assertEqual([s.step_order for s in steps], [1, 2, 3])
        foreign = self.client.post(
            reverse("ui3:step_reorder", args=[self.other_protocol.id]),
            {"order": str(created[0].id)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(foreign.status_code, 403)

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

    def test_share_protocol_copies_steps_onto_peer(self):
        env = VirtualEnvironment.objects.create(name="py310", ve_type="conda", value="x", user=self.user)
        Step.objects.create(
            parent=self.protocol,
            software="cutadapt",
            parameter="-q 20",
            step_order=1,
            hash=compute_step_hash("cutadapt", "-q 20"),
            user=self.user,
            env=env,
            force_local=1,
            version_check="cutadapt --version",
            cpu_prior=2,
            mem_prior=4,
            disk_prior=8,
            gpu_step=1,
            step_comment="trim",
            specify_output="trimmed.fq",
        )
        ProtocolShortcut.objects.create(
            user=self.user,
            protocol=self.protocol,
            label="Open",
            href_template="/ui/jobs/{id}",
        )
        self.protocol.template = ""
        self.protocol.save(update_fields=["template"])
        self.login()
        detail = self.client.get(reverse("ui3:protocol_detail", args=[self.protocol.id]))
        self.assertContains(detail, "Share with a peer")
        self.assertContains(detail, reverse("ui3:protocol_share", args=[self.protocol.id]))
        response = self.client.post(
            reverse("ui3:protocol_share", args=[self.protocol.id]),
            {"peer": "bob"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Shared &#x27;RNA-seq&#x27; with bob.")
        copies = ProtocolList.objects.filter(name="RNA-seq", user=self.other)
        self.assertEqual(copies.count(), 1)
        dest = copies.get()
        self.assertEqual(dest.description, "demo")
        self.assertEqual(dest.user, self.other)
        self.assertNotEqual(dest.id, self.protocol.id)
        step = protocol_steps(dest).get()
        self.assertEqual(step.software, "cutadapt")
        self.assertEqual(step.parameter, "-q 20")
        self.assertEqual(step.user, self.other)
        copied_env = step.env
        self.assertEqual(copied_env.user, self.other)
        self.assertNotEqual(copied_env.id, env.id)
        self.assertEqual(copied_env.name, "py310")
        self.assertEqual(copied_env.value, "x")
        self.assertEqual(copied_env.ve_type, "conda")
        self.assertEqual(VirtualEnvironment.objects.filter(name="py310", user=self.user).count(), 1)
        self.assertEqual(step.force_local, 1)
        self.assertEqual(step.version_check, "cutadapt --version")
        self.assertEqual(step.cpu_prior, 2)
        self.assertEqual(step.mem_prior, 4)
        self.assertEqual(step.disk_prior, 8)
        self.assertEqual(step.gpu_step, 1)
        self.assertEqual(step.step_comment, "trim")
        self.assertEqual(step.specify_output, "trimmed.fq")
        self.assertEqual(step.hash, compute_step_hash("cutadapt", "-q 20"))
        self.assertFalse(ProtocolShortcut.objects.filter(protocol=dest).exists())
        self.assertEqual(protocol_steps(self.protocol).count(), 1)

    def test_share_creates_missing_refs_and_environments(self):
        private_env = VirtualEnvironment.objects.create(
            name="analysis",
            ve_type="conda",
            value="analysis",
            recipe="conda install cutadapt",
            activation_command="source /opt/conda.sh",
            user=self.user,
        )
        public_env = VirtualEnvironment.objects.create(
            name="base", ve_type="conda", value="base", user=None,
        )
        Reference.objects.create(name="genome", path="/data/genome.fa", description="hg38", user=self.user)
        Reference.objects.create(name="adapters", path="/data/adapters.fa", description="shared", user=None)
        VirtualEnvironment.objects.create(
            name="analysis", ve_type="venv", value="bob-analysis", recipe="already", user=self.other,
        )
        Reference.objects.create(name="genome", path="/bob/genome.fa", description="bob", user=self.other)
        Step.objects.create(
            parent=self.protocol,
            software="cutadapt",
            parameter="-a {{adapters}} -g {{genome||/fallback.fa}} {{InputFile}}",
            step_order=1,
            hash=compute_step_hash("cutadapt", "x"),
            user=self.user,
            env=private_env,
        )
        Step.objects.create(
            parent=self.protocol,
            software="echo",
            parameter="{{sample.name}}",
            step_order=2,
            hash=compute_step_hash("echo", "y"),
            user=self.user,
            env=public_env,
        )
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_share", args=[self.protocol.id]),
            {"peer": "bob"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Added environments")
        self.assertNotContains(response, "Added references")
        steps = list(protocol_steps(ProtocolList.objects.get(name="RNA-seq", user=self.other)))
        self.assertEqual(steps[0].env.user, self.other)
        self.assertEqual(steps[0].env.value, "bob-analysis")
        self.assertEqual(steps[0].env.recipe, "already")
        self.assertEqual(steps[1].env, public_env)
        self.assertEqual(Reference.objects.filter(name="genome", user=self.other).get().path, "/bob/genome.fa")
        self.assertFalse(Reference.objects.filter(name="adapters", user=self.other).exists())
        self.assertFalse(Reference.objects.filter(name="InputFile").exists())
        self.assertFalse(Reference.objects.filter(name="sample").exists())
        self.assertEqual(VirtualEnvironment.objects.filter(name="base").count(), 1)

    def test_share_creates_template_environment_and_reference(self):
        VirtualEnvironment.objects.create(
            name="analysis",
            ve_type="conda",
            value="analysis",
            recipe="conda install bwa",
            activation_command="source /opt/conda.sh",
            user=self.user,
        )
        Reference.objects.create(name="genome", path="/data/genome.fa", description="hg38", user=self.user)
        self.protocol.template = (
            '{"pipeline":[{"software":"bwa","parameter":"mem {{genome}}","env":"analysis"}]}'
        )
        self.protocol.save(update_fields=["template"])
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_share", args=[self.protocol.id]),
            {"peer": "bob"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Added environments analysis and references genome.")
        copied_env = VirtualEnvironment.objects.get(name="analysis", user=self.other)
        self.assertEqual(copied_env.value, "analysis")
        self.assertEqual(copied_env.recipe, "conda install bwa")
        self.assertEqual(copied_env.activation_command, "source /opt/conda.sh")
        copied_ref = Reference.objects.get(name="genome", user=self.other)
        self.assertEqual(copied_ref.path, "/data/genome.fa")
        self.assertEqual(copied_ref.description, "hg38")
        self.assertTrue(VirtualEnvironment.objects.filter(name="analysis", user=self.user).exists())

    def test_share_keeps_template_and_lands_on_named_account(self):
        from django.contrib.auth.models import User

        project = User.objects.create_user("lab-project", password="secret")
        profile = self.other.queuedb_profile_related
        profile.delegate = project
        profile.save(update_fields=["delegate"])
        self.protocol.template = '{"samples":[],"blocks":{},"pipeline":[]}'
        self.protocol.save(update_fields=["template"])
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_share", args=[self.protocol.id]),
            {"peer": "bob"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("select={}".format(self.protocol.id), response["Location"])
        dest = ProtocolList.objects.get(name="RNA-seq", user=self.other)
        self.assertEqual(dest.template, self.protocol.template)
        self.assertNotEqual(dest.user, project)

    def test_share_rejects_self_unknown_and_foreign(self):
        self.login()
        url = reverse("ui3:protocol_share", args=[self.protocol.id])
        self_share = self.client.post(url, {"peer": "alice"}, HTTP_HX_REQUEST="true")
        self.assertEqual(self_share.status_code, 400)
        self.assertEqual(self_share["HX-Retarget"], "#toast-root")
        self.assertContains(self_share, "You can not share a protocol with yourself.", status_code=400)
        missing = self.client.post(url, {"peer": "nobody"}, HTTP_HX_REQUEST="true")
        self.assertEqual(missing.status_code, 400)
        self.assertContains(missing, "doesn&#x27;t exist", status_code=400)
        blank = self.client.post(url, {"peer": "  "}, HTTP_HX_REQUEST="true")
        self.assertEqual(blank.status_code, 400)
        foreign = self.client.post(
            reverse("ui3:protocol_share", args=[self.other_protocol.id]),
            {"peer": "alice"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(foreign.status_code, 403)
        public = ProtocolList.objects.create(name="shared-public", user=None)
        denied = self.client.post(
            reverse("ui3:protocol_share", args=[public.id]),
            {"peer": "bob"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(denied.status_code, 403)
        public_page = self.client.get(reverse("ui3:protocol_detail", args=[public.id]))
        self.assertNotContains(public_page, "Share with a peer")
        self.assertFalse(ProtocolList.objects.filter(name="RNA-seq", user=self.other).exists())

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
        self.assertContains(detail, "shared-public")
        self.assertContains(detail, "No description")
        self.assertContains(detail, "Version")
        self.assertContains(detail, "pub1")
        self.assertNotContains(detail, 'name="ver"')
        self.assertNotContains(detail, 'name="description"')
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
        self.assertContains(listed, 'id="protocol-shortcuts"')
        self.assertNotContains(listed, 'id="protocol-shortcuts" open')
        self.assertContains(listed, "Evaluate")
        self.assertContains(listed, "/ui/eval/{id}")
        toggle = self.client.post(reverse("ui3:shortcut_toggle", args=[sc.id]))
        self.assertIn(toggle.status_code, (200, 302))
        sc.refresh_from_db()
        self.assertEqual(sc.active, 0)
        modal = self.client.get(reverse("ui3:shortcut_edit", args=[sc.id]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "ui-modal-lg")
        self.assertContains(modal, "ui-modal-editor")
        self.assertContains(modal, 'name="href_template"')
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
        self.assertContains(response, 'name="description"')
        self.assertNotContains(response, "No description")
        self.assertNotContains(response, 'class="text-lg font-semibold truncate"')
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
        self.assertContains(response, "Search by name, description, or id")

    def test_search_matches_description(self):
        ProtocolList.objects.create(
            name="ATAC",
            description="call peaks from tn5 cuts",
            user=self.user,
            ver="atac1",
        )
        other = ProtocolList.objects.create(
            name="WGBS",
            description="bisulfite methylation",
            user=self.user,
            ver="wgbs1",
        )
        self.login()
        by_desc = self.client.get(reverse("ui3:protocols"), {"q": "peaks"})
        self.assertContains(by_desc, "ATAC")
        self.assertNotContains(by_desc, "WGBS")
        by_name = self.client.get(reverse("ui3:protocols"), {"q": "WGBS"})
        self.assertContains(by_name, "WGBS")
        self.assertNotContains(by_name, "ATAC")
        by_id = self.client.get(reverse("ui3:protocols"), {"q": str(other.id)})
        self.assertContains(by_id, "WGBS")
        self.assertNotContains(by_id, "ATAC")
        combo = self.client.get(reverse("ui3:protocol_options"), {"combo_q": "tn5"})
        self.assertContains(combo, "ATAC")
        self.assertNotContains(combo, "WGBS")

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
        named = self.client.get(reverse("ui3:environment_options"), {
            "combo_q": "py3", "by": "name", "empty": "Default worker environment",
        })
        self.assertContains(named, 'data-value="py310"')
        self.assertContains(named, "Default worker environment")
        self.assertNotContains(named, 'data-value="{}"'.format(
            VirtualEnvironment.objects.get(name="py310").id
        ))
        missing = self.client.get(reverse("ui3:environment_options"), {
            "by": "name", "pin_name": "gone", "empty": "Default worker environment",
        })
        self.assertContains(missing, 'data-value="gone"')
        self.assertContains(missing, "gone (unavailable)")

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
        self.assertContains(response, "filter environments")
        self.assertContains(response, 'data-combo-nosubmit')
        self.assertContains(response, "ui-modal-lg")
        self.assertContains(response, "ui-modal-editor")
        self.assertContains(response, 'data-ui3-parameter-rows="12"')
        self.assertContains(response, 'rows="12"')

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
        self.assertContains(get, "ui-modal-lg")
        self.assertContains(get, "ui-modal-editor")
        self.assertContains(get, 'data-ui3-parameter-rows="12"')
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

    def test_export_protocol_json(self):
        import json

        from QueueDB.models import Reference

        Step.objects.create(
            parent=self.protocol,
            software="bwa",
            parameter="mem {{hg38}} {InputFile}",
            step_order=1,
            hash=compute_step_hash("bwa", "mem {{hg38}} {InputFile}"),
            version_check="bwa --version",
            user=self.user,
        )
        Reference.objects.create(name="hg38", path="/refs/hg38.fa", description="human genome", user=self.user)
        self.login()
        page = self.client.get(reverse("ui3:protocol_detail", args=[self.protocol.id]))
        self.assertContains(page, reverse("ui3:protocol_export", args=[self.protocol.id]))
        response = self.client.get(reverse("ui3:protocol_export", args=[self.protocol.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        self.assertIn("RNA-seq.json", response["Content-Disposition"])
        data = json.loads(response.content.decode())
        self.assertEqual(data["name"], "RNA-seq")
        self.assertEqual(data["description"], "demo")
        self.assertEqual(len(data["step"]), 1)
        self.assertEqual(data["step"][0]["software"], "bwa")
        self.assertEqual(data["step"][0]["parameter"], "mem {{hg38}} {InputFile}")
        self.assertEqual(data["step"][0]["version_check"], "bwa --version")
        self.assertEqual(data["reference"]["hg38"], "human genome")

        public = ProtocolList.objects.create(name="public-export", description="ok", user=None, ver="px")
        public_export = self.client.get(reverse("ui3:protocol_export", args=[public.id]))
        self.assertEqual(public_export.status_code, 200)
        self.assertEqual(json.loads(public_export.content.decode())["name"], "public-export")

        forbidden = self.client.get(reverse("ui3:protocol_export", args=[self.other_protocol.id]))
        self.assertEqual(forbidden.status_code, 403)

    def test_import_protocol_json(self):
        import json

        from django.core.files.uploadedfile import SimpleUploadedFile
        from QueueDB.models import Reference

        payload = {
            "name": "Imported ATAC",
            "description": "from json",
            "ver": "ignored",
            "step": [
                {
                    "software": "macs2",
                    "parameter": "callpeak -t {{hg38}}",
                    "step_order": 1,
                    "version_check": "",
                }
            ],
            "reference": {"hg38": "human genome"},
        }
        self.login()
        missing_ref = self.client.post(
            reverse("ui3:protocol_import"),
            {"file": SimpleUploadedFile("atac.json", json.dumps(payload).encode(), content_type="application/json")},
        )
        self.assertEqual(missing_ref.status_code, 302)
        proto = ProtocolList.objects.get(name="Imported ATAC", user=self.user)
        self.assertEqual(proto.description, "from json")
        steps = list(protocol_steps(proto))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].software, "macs2")
        self.assertEqual(steps[0].parameter, "callpeak -t {{hg38}}")
        self.assertIn("select={}".format(proto.id), missing_ref["Location"])

        dup = self.client.post(
            reverse("ui3:protocol_import"),
            {"file": SimpleUploadedFile("atac.json", json.dumps(payload).encode(), content_type="application/json")},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(dup.status_code, 400)

        bad = self.client.post(
            reverse("ui3:protocol_import"),
            {"file": SimpleUploadedFile("bad.json", b"not-json", content_type="application/json")},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(bad.status_code, 400)

        empty = self.client.post(reverse("ui3:protocol_import"), HTTP_HX_REQUEST="true")
        self.assertEqual(empty.status_code, 400)

        Reference.objects.create(name="hg38", path="/refs/hg38.fa", description="human", user=self.user)
        payload["name"] = "Imported ATAC 2"
        ok_refs = self.client.post(
            reverse("ui3:protocol_import"),
            {"file": SimpleUploadedFile("atac2.json", json.dumps(payload).encode(), content_type="application/json")},
        )
        self.assertEqual(ok_refs.status_code, 302)
        self.assertTrue(ProtocolList.objects.filter(name="Imported ATAC 2", user=self.user).exists())

    def test_import_protocol_json_roundtrip(self):
        import json

        from django.core.files.uploadedfile import SimpleUploadedFile

        Step.objects.create(
            parent=self.protocol,
            software="cutadapt",
            parameter="-q 20",
            step_order=1,
            hash=compute_step_hash("cutadapt", "-q 20"),
            user=self.user,
        )
        self.login()
        exported = self.client.get(reverse("ui3:protocol_export", args=[self.protocol.id]))
        data = json.loads(exported.content.decode())
        data["name"] = "RNA-seq from json"
        imported = self.client.post(
            reverse("ui3:protocol_import"),
            {"file": SimpleUploadedFile("rna.json", json.dumps(data).encode(), content_type="application/json")},
        )
        self.assertEqual(imported.status_code, 302)
        dest = ProtocolList.objects.get(name="RNA-seq from json", user=self.user)
        dest_steps = list(protocol_steps(dest))
        self.assertEqual([s.software for s in dest_steps], ["cutadapt"])
        self.assertEqual(dest_steps[0].parameter, "-q 20")
        self.assertEqual(dest.description, "demo")

    def test_export_and_import_environment_recipes(self):
        import json

        from django.core.files.uploadedfile import SimpleUploadedFile
        from QueueDB.models import VirtualEnvironment

        env = VirtualEnvironment.objects.create(
            name="py310",
            ve_type="conda",
            value="bioqueue",
            activation_command="source /opt/conda.sh",
            recipe="name: bioqueue\ndependencies:\n  - python=3.10\n",
            user=self.user,
        )
        for order, software in ((1, "bwa"), (2, "samtools")):
            Step.objects.create(
                parent=self.protocol,
                software=software,
                parameter="run",
                step_order=order,
                hash=compute_step_hash(software, "run"),
                user=self.user,
                env=env,
            )
        self.login()
        exported = self.client.get(reverse("ui3:protocol_export", args=[self.protocol.id]))
        data = json.loads(exported.content.decode())
        self.assertEqual([step["env"] for step in data["step"]], ["py310", "py310"])
        self.assertEqual(set(data["environment"]), {"py310"})
        entry = data["environment"]["py310"]
        self.assertEqual(entry["ve_type"], "conda")
        self.assertEqual(entry["value"], "bioqueue")
        self.assertIn("python=3.10", entry["recipe"])
        self.assertNotIn("activation_command", entry)

        data["name"] = "RNA-seq imported"
        response = self.client.post(
            reverse("ui3:protocol_import"),
            {"file": SimpleUploadedFile("rna.json", json.dumps(data).encode(), content_type="application/json")},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        imported = ProtocolList.objects.get(name="RNA-seq imported", user=self.user)
        steps = list(protocol_steps(imported))
        self.assertEqual(steps[0].env_id, env.id)
        self.assertEqual(steps[1].env_id, env.id)
        env.refresh_from_db()
        self.assertEqual(env.activation_command, "source /opt/conda.sh")
        self.assertEqual(env.value, "bioqueue")

    def test_import_creates_environment_rows_without_replacing_existing(self):
        import json

        from django.contrib.messages import get_messages
        from django.core.files.uploadedfile import SimpleUploadedFile
        from QueueDB.models import VirtualEnvironment

        owned = VirtualEnvironment.objects.create(
            name="py310", ve_type="conda", value="local-bioqueue", activation_command="source /mine.sh",
            recipe="", user=self.user,
        )
        public = VirtualEnvironment.objects.create(
            name="shared", ve_type="venv", value="/opt/shared", recipe="flask==1.0\n", user=None,
        )
        payload = {
            "name": "with envs",
            "step": [
                {"software": "echo", "parameter": "a", "step_order": 1, "env": "newenv"},
                {"software": "echo", "parameter": "b", "step_order": 2, "env": "py310"},
                {"software": "echo", "parameter": "c", "step_order": 3, "env": "shared"},
            ],
            "environment": {
                "newenv": {"ve_type": "venv", "recipe": "requests==2\n", "value": "/opt/new"},
                "blank": {"ve_type": "conda", "recipe": "", "value": ""},
                "py310": {"ve_type": "conda", "recipe": "name: other\n", "value": "other"},
                "shared": {"ve_type": "conda", "recipe": "flask==2\n", "value": "/elsewhere"},
            },
        }
        self.login()
        response = self.client.post(
            reverse("ui3:protocol_import"),
            {"file": SimpleUploadedFile("envs.json", json.dumps(payload).encode(), content_type="application/json")},
        )
        self.assertEqual(response.status_code, 302)
        created = VirtualEnvironment.objects.get(name="newenv", user=self.user)
        self.assertEqual(created.ve_type, "venv")
        self.assertEqual(created.value, "/opt/new")
        self.assertEqual(created.recipe, "requests==2\n")
        self.assertFalse(created.activation_command)
        blank = VirtualEnvironment.objects.get(name="blank", user=self.user)
        self.assertEqual(blank.value, "blank")
        self.assertEqual(blank.recipe, "")
        owned.refresh_from_db()
        self.assertEqual(owned.value, "local-bioqueue")
        self.assertEqual(owned.activation_command, "source /mine.sh")
        self.assertEqual(owned.recipe, "name: other\n")
        public.refresh_from_db()
        self.assertEqual(public.value, "/opt/shared")
        self.assertEqual(public.recipe, "flask==1.0\n")
        self.assertFalse(VirtualEnvironment.objects.filter(name="shared", user=self.user).exists())
        steps = list(protocol_steps(ProtocolList.objects.get(name="with envs", user=self.user)))
        self.assertEqual(steps[0].env_id, created.id)
        self.assertEqual(steps[1].env_id, owned.id)
        self.assertEqual(steps[2].env_id, public.id)
        notes = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("shared" in note and "left unchanged" in note for note in notes))
        self.assertFalse(any("py310" in note and "left unchanged" in note for note in notes))
