from django.urls import reverse

from QueueDB.models import Reference
from ui.tests import Ui3TestCase


class ReferenceTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        self.ref = Reference.objects.create(
            name="hg38",
            path="/refs/hg38.fa",
            description="genome",
            user=self.user,
        )
        Reference.objects.create(
            name="secret-ref",
            path="/hidden",
            description="",
            user=self.other,
        )

    def test_list_own_references(self):
        self.login()
        response = self.client.get(reverse("ui3:references"))
        self.assertContains(response, "hg38")
        self.assertNotContains(response, "secret-ref")

    def test_create_reference(self):
        self.login()
        response = self.client.post(
            reverse("ui3:reference_create"),
            {"name": "mm10", "path": "/refs/mm10.fa", "description": "mouse"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Reference.objects.filter(name="mm10", user=self.user).exists())

    def test_create_requires_name_and_path(self):
        self.login()
        response = self.client.post(reverse("ui3:reference_create"), {"name": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Reference.objects.filter(name="x").exists())

    def test_edit_and_delete(self):
        self.login()
        modal = self.client.get(reverse("ui3:reference_edit", args=[self.ref.id]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "ui-modal-lg")
        self.assertContains(modal, "ui-modal-editor")
        self.assertContains(modal, 'name="path"')
        self.assertContains(modal, "Name")
        self.assertContains(modal, "Path")
        self.assertContains(modal, "Description")
        response = self.client.post(
            reverse("ui3:reference_edit", args=[self.ref.id]),
            {"name": "hg38.p14", "path": "/refs/hg38.p14.fa", "description": "updated"},
        )
        self.assertEqual(response.status_code, 302)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.name, "hg38.p14")
        response = self.client.post(reverse("ui3:reference_delete", args=[self.ref.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Reference.objects.filter(pk=self.ref.id).exists())

    def test_cannot_delete_foreign_reference(self):
        foreign = Reference.objects.get(name="secret-ref")
        self.login()
        response = self.client.post(reverse("ui3:reference_delete", args=[foreign.id]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_mutate_public_reference(self):
        public = Reference.objects.create(name="public-ref", path="/refs/pub.fa", user=None)
        self.login()
        listed = self.client.get(reverse("ui3:references"))
        self.assertContains(listed, "public-ref")
        self.assertContains(listed, "public")
        edit = self.client.post(
            reverse("ui3:reference_edit", args=[public.id]),
            {"name": "hacked", "path": "/tmp/x"},
        )
        self.assertEqual(edit.status_code, 403)
        public.refresh_from_db()
        self.assertEqual(public.name, "public-ref")
        delete = self.client.post(reverse("ui3:reference_delete", args=[public.id]))
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(Reference.objects.filter(pk=public.id).exists())

    def test_list_has_reference_pager(self):
        self.login()
        response = self.client.get(reverse("ui3:references"))
        self.assertContains(response, "reference")
        self.assertContains(response, "page size")
        self.assertContains(response, 'id="reference-filters"')
        self.assertContains(response, "page-head")

    def test_create_rejects_too_long_name(self):
        self.login()
        response = self.client.post(
            reverse("ui3:reference_create"),
            {"name": "r" * 256, "path": "/refs/x"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Reference.objects.filter(name="r" * 256).exists())

    def test_htmx_create_validation_is_error(self):
        self.login()
        response = self.client.post(
            reverse("ui3:reference_create"),
            {"name": "only-name"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Reference.objects.filter(name="only-name").exists())

    def test_create_form_resets_after_success(self):
        self.login()
        response = self.client.get(reverse("ui3:references"))
        self.assertContains(response, "hx-on::after-request")
        self.assertContains(response, "this.reset()")
        self.assertContains(response, 'maxlength="255"')
        self.assertContains(response, 'maxlength="500"')

    def test_htmx_search_partial(self):
        self.login()
        response = self.client.get(
            reverse("ui3:references"),
            {"q": "hg38"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "hg38")
        self.assertNotContains(response, "<html")
