from django.urls import reverse

from QueueDB.models import Step, VirtualEnvironment
from ui.tests import Ui3TestCase


class EnvironmentTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        self.env = VirtualEnvironment.objects.create(
            name="py310",
            ve_type="conda",
            value="bioqueue",
            activation_command="conda activate bioqueue",
            user=self.user,
        )
        VirtualEnvironment.objects.create(
            name="secret-env",
            ve_type="venv",
            value="/hidden",
            user=self.other,
        )

    def test_list_own_and_public(self):
        public = VirtualEnvironment.objects.create(name="public-env", ve_type="conda", value="shared", user=None)
        self.login()
        response = self.client.get(reverse("ui3:environments"))
        self.assertContains(response, "py310")
        self.assertContains(response, "public-env")
        self.assertContains(response, "public")
        self.assertNotContains(response, "secret-env")
        self.assertContains(response, 'id="environment-filters"')
        self.assertContains(response, "page-head")
        self.assertTrue(public.id)

    def test_create_environment(self):
        self.login()
        response = self.client.post(
            reverse("ui3:environment_create"),
            {"name": "r-base", "ve_type": "venv", "value": "/opt/r", "activation_command": "source /opt/r/bin/activate"},
        )
        self.assertEqual(response.status_code, 302)
        env = VirtualEnvironment.objects.get(name="r-base", user=self.user)
        self.assertEqual(env.ve_type, "venv")
        self.assertEqual(env.value, "/opt/r")

    def test_create_requires_name_and_value(self):
        self.login()
        response = self.client.post(reverse("ui3:environment_create"), {"name": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(VirtualEnvironment.objects.filter(name="x").exists())

    def test_edit_and_delete(self):
        self.login()
        modal = self.client.get(reverse("ui3:environment_edit", args=[self.env.id]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "ui-modal-lg")
        self.assertContains(modal, "ui-modal-editor")
        self.assertContains(modal, 'name="value"')
        self.assertContains(modal, "Name")
        self.assertContains(modal, "Type")
        self.assertContains(modal, "Value")
        self.assertContains(modal, "Activation command")
        self.assertContains(modal, "Recipe")
        response = self.client.post(
            reverse("ui3:environment_edit", args=[self.env.id]),
            {"name": "py311", "ve_type": "conda", "value": "bioqueue2", "activation_command": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.env.refresh_from_db()
        self.assertEqual(self.env.name, "py311")
        self.assertEqual(self.env.value, "bioqueue2")
        response = self.client.post(reverse("ui3:environment_delete", args=[self.env.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(VirtualEnvironment.objects.filter(pk=self.env.id).exists())

    def test_cannot_mutate_foreign_environment(self):
        foreign = VirtualEnvironment.objects.get(name="secret-env")
        self.login()
        response = self.client.post(reverse("ui3:environment_delete", args=[foreign.id]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_mutate_public_environment(self):
        public = VirtualEnvironment.objects.create(name="shared-ve", ve_type="conda", value="base", user=None)
        self.login()
        listed = self.client.get(reverse("ui3:environments"))
        self.assertContains(listed, "shared-ve")
        edit = self.client.post(
            reverse("ui3:environment_edit", args=[public.id]),
            {"name": "hacked", "ve_type": "conda", "value": "x"},
        )
        self.assertEqual(edit.status_code, 403)
        public.refresh_from_db()
        self.assertEqual(public.name, "shared-ve")
        delete = self.client.post(reverse("ui3:environment_delete", args=[public.id]))
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(VirtualEnvironment.objects.filter(pk=public.id).exists())

    def test_cannot_delete_environment_in_use(self):
        Step.objects.create(
            parent=self.protocol,
            software="echo",
            parameter="",
            env=self.env,
            step_order=1,
            hash="h1",
            user=self.user,
        )
        self.login()
        response = self.client.post(reverse("ui3:environment_delete", args=[self.env.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(VirtualEnvironment.objects.filter(pk=self.env.id).exists())

    def test_create_rejects_too_long_name(self):
        self.login()
        response = self.client.post(
            reverse("ui3:environment_create"),
            {"name": "e" * 51, "ve_type": "conda", "value": "x"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(VirtualEnvironment.objects.filter(name="e" * 51).exists())

    def test_htmx_create_validation_is_error(self):
        self.login()
        response = self.client.post(
            reverse("ui3:environment_create"),
            {"name": "only-name"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(VirtualEnvironment.objects.filter(name="only-name").exists())

    def test_create_form_resets_after_success(self):
        self.login()
        response = self.client.get(reverse("ui3:environments"))
        self.assertContains(response, "hx-on::after-request")
        self.assertContains(response, "this.reset()")
        self.assertContains(response, 'maxlength="50"')

    def test_htmx_search_partial(self):
        self.login()
        response = self.client.get(
            reverse("ui3:environments"),
            {"q": "py310"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "py310")
        self.assertNotContains(response, "<html")

    def test_create_and_edit_recipe(self):
        self.login()
        created = self.client.post(
            reverse("ui3:environment_create"),
            {
                "name": "analysis",
                "ve_type": "conda",
                "value": "analysis",
                "recipe": "name: analysis\ndependencies:\n  - python=3.10\n",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(created.status_code, 200)
        env = VirtualEnvironment.objects.get(name="analysis", user=self.user)
        self.assertIn("python=3.10", env.recipe)
        self.assertContains(created, ">yes<")
        edited = self.client.post(
            reverse("ui3:environment_edit", args=[env.id]),
            {
                "name": "analysis",
                "ve_type": "conda",
                "value": "analysis",
                "activation_command": "",
                "recipe": "python==3.11\n",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(edited.status_code, 200)
        env.refresh_from_db()
        self.assertEqual(env.recipe, "python==3.11\n")
        found = self.client.get(reverse("ui3:environments"), {"q": "python==3.11"}, HTTP_HX_REQUEST="true")
        self.assertContains(found, "analysis")
