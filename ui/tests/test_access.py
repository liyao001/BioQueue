"""Cross-access grant page: create, update, revoke, and ownership."""

from django.contrib.auth.models import User
from django.urls import reverse

from QueueDB.models import CrossAccess
from ui.services import CrossAccessError, grant_cross_access, owned_jobs
from ui.tests import Ui3TestCase


class CrossAccessPageTests(Ui3TestCase):
    def test_page_lists_outgoing_and_incoming(self):
        CrossAccess.objects.create(user=self.user, grantee=self.other, allow_read=1, allow_write=0)
        self.login()
        response = self.client.get(reverse("ui3:cross_access"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "People who can use your jobs")
        self.assertContains(response, "Shared with you")
        self.assertContains(response, "bob")
        self.assertContains(response, 'id="access-panel"')

        self.login("bob")
        incoming = self.client.get(reverse("ui3:cross_access"))
        self.assertContains(incoming, "alice")
        self.assertContains(incoming, "No one else can open your jobs yet")

    def test_anonymous_redirects(self):
        response = self.client.get(reverse("ui3:cross_access"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ui/login/", response.url)

    def test_create_grants_read_and_shows_shared_jobs(self):
        job = self.make_job(job_name="visible-shared")
        self.login()
        response = self.client.post(
            reverse("ui3:cross_access_create"),
            {"username": "bob", "allow_read": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "bob")
        self.assertContains(response, "Saved access for bob")
        grant = CrossAccess.objects.get(user=self.user, grantee=self.other)
        self.assertEqual(grant.allow_read, 1)
        self.assertEqual(grant.allow_write, 0)
        self.login("bob")
        shared = self.client.get(reverse("ui3:jobs"), {"scope": "shared"})
        self.assertContains(shared, job.job_name)

    def test_create_rejects_unknown_self_and_empty_flags(self):
        self.login()
        missing = self.client.post(
            reverse("ui3:cross_access_create"),
            {"username": "nobody", "allow_read": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertContains(missing, "share with", status_code=400)

        own = self.client.post(
            reverse("ui3:cross_access_create"),
            {"username": "alice", "allow_read": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(own.status_code, 400)
        self.assertContains(own, "already owns these jobs", status_code=400)

        blank = self.client.post(
            reverse("ui3:cross_access_create"),
            {"username": "bob"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(blank.status_code, 400)
        self.assertContains(blank, "Allow read or write", status_code=400)
        self.assertFalse(CrossAccess.objects.filter(user=self.user, grantee=self.other).exists())

    def test_repeat_create_updates_the_same_row(self):
        self.login()
        self.client.post(
            reverse("ui3:cross_access_create"),
            {"username": "bob", "allow_read": "1"},
            HTTP_HX_REQUEST="true",
        )
        again = self.client.post(
            reverse("ui3:cross_access_create"),
            {"username": "bob", "allow_read": "1", "allow_write": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(again.status_code, 200)
        self.assertContains(again, "Updated access for bob")
        grant = CrossAccess.objects.get(user=self.user, grantee=self.other)
        self.assertEqual(grant.allow_write, 1)
        self.assertEqual(CrossAccess.objects.filter(user=self.user, grantee=self.other).count(), 1)

    def test_grant_uses_the_recipients_delegate(self):
        lab = User.objects.create_user("lab", password="secret")
        profile = self.other.queuedb_profile_related
        profile.delegate = lab
        profile.save(update_fields=["delegate"])
        grant, created = grant_cross_access(self.user, "bob", allow_read=True)
        self.assertTrue(created)
        self.assertEqual(grant.grantee_id, lab.id)
        job = self.make_job(job_name="delegated-share")
        self.login("bob")
        shared = self.client.get(reverse("ui3:jobs"), {"scope": "shared"})
        self.assertContains(shared, job.job_name)
        self.assertEqual(list(owned_jobs(self.other, scope="shared")), [job])

    def test_other_user_cannot_change_or_revoke(self):
        grant = CrossAccess.objects.create(user=self.user, grantee=self.other, allow_read=1)
        self.login("bob")
        updated = self.client.post(
            reverse("ui3:cross_access_update", args=[grant.id]),
            {"allow_read": "0"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(updated.status_code, 403)
        revoked = self.client.post(
            reverse("ui3:cross_access_delete", args=[grant.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(revoked.status_code, 403)
        grant.refresh_from_db()
        self.assertEqual(grant.allow_read, 1)

    def test_update_and_revoke(self):
        grant = CrossAccess.objects.create(user=self.user, grantee=self.other, allow_read=1, allow_write=0)
        duplicate = CrossAccess.objects.create(user=self.user, grantee=self.other, allow_read=1, allow_write=1)
        self.login()
        response = self.client.post(
            reverse("ui3:cross_access_update", args=[grant.id]),
            {"allow_read": "0"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "read off")
        grant.refresh_from_db()
        self.assertEqual(grant.allow_read, 0)
        self.assertFalse(CrossAccess.objects.filter(pk=duplicate.id).exists())

        missing = self.client.post(
            reverse("ui3:cross_access_update", args=[grant.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(missing.status_code, 400)

        removed = self.client.post(
            reverse("ui3:cross_access_delete", args=[grant.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(removed.status_code, 200)
        self.assertContains(removed, "No one else can open your jobs yet")
        self.assertFalse(CrossAccess.objects.filter(user=self.user, grantee=self.other).exists())

    def test_service_rejects_a_grant_to_yourself(self):
        with self.assertRaises(CrossAccessError):
            grant_cross_access(self.user, "alice", allow_read=True)
