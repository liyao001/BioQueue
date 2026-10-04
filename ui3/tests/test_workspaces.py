from django.urls import reverse

from QueueDB.models import Workspace
from ui3.tests import Ui3TestCase


class WorkspaceTests(Ui3TestCase):
    def test_list_own_workspaces(self):
        Workspace.objects.create(name="secret-ws", user=self.other)
        self.login()
        response = self.client.get(reverse("ui3:workspaces"))
        self.assertContains(response, "ws1")
        self.assertNotContains(response, "secret-ws")
        self.assertContains(response, "Workspaces")
        self.assertContains(response, 'id="workspace-filters"')
        self.assertContains(response, "page-head")

    def test_create_workspace(self):
        self.login()
        response = self.client.post(
            reverse("ui3:workspace_create"),
            {"name": "lab-a", "description": "primary"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Workspace.objects.filter(name="lab-a", user=self.user).exists())

    def test_create_requires_name(self):
        self.login()
        response = self.client.post(reverse("ui3:workspace_create"), {"description": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Workspace.objects.filter(description="x").exists())

    def test_edit_and_delete(self):
        self.login()
        modal = self.client.get(reverse("ui3:workspace_edit", args=[self.workspace.id]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "ui-modal-lg")
        self.assertContains(modal, "ui-modal-editor")
        self.assertContains(modal, "Name")
        self.assertContains(modal, "Description")
        response = self.client.post(
            reverse("ui3:workspace_edit", args=[self.workspace.id]),
            {"name": "ws1-renamed", "description": "updated"},
        )
        self.assertEqual(response.status_code, 302)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.name, "ws1-renamed")
        response = self.client.post(reverse("ui3:workspace_delete", args=[self.workspace.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Workspace.objects.filter(pk=self.workspace.id).exists())

    def test_cannot_mutate_foreign_workspace(self):
        foreign = Workspace.objects.create(name="bob-ws", user=self.other)
        self.login()
        edit = self.client.post(
            reverse("ui3:workspace_edit", args=[foreign.id]),
            {"name": "hacked"},
        )
        self.assertEqual(edit.status_code, 403)
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, "bob-ws")
        delete = self.client.post(reverse("ui3:workspace_delete", args=[foreign.id]))
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(Workspace.objects.filter(pk=foreign.id).exists())

    def test_cannot_delete_workspace_in_use(self):
        self.make_job(workspace=self.workspace)
        self.login()
        response = self.client.post(reverse("ui3:workspace_delete", args=[self.workspace.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Workspace.objects.filter(pk=self.workspace.id).exists())

    def test_create_rejects_too_long_name(self):
        self.login()
        response = self.client.post(
            reverse("ui3:workspace_create"),
            {"name": "w" * 256},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Workspace.objects.filter(name="w" * 256).exists())

    def test_htmx_create_validation_is_error(self):
        self.login()
        response = self.client.post(
            reverse("ui3:workspace_create"),
            {"description": "x"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Workspace.objects.filter(description="x").exists())

    def test_create_form_resets_after_success(self):
        self.login()
        response = self.client.get(reverse("ui3:workspaces"))
        self.assertContains(response, "hx-on::after-request")
        self.assertContains(response, "this.reset()")
        self.assertContains(response, 'maxlength="255"')

    def test_htmx_search_partial(self):
        self.login()
        response = self.client.get(
            reverse("ui3:workspaces"),
            {"q": "ws1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ws1")
        self.assertNotContains(response, "<html")
