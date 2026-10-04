from django.contrib.auth.models import User
from django.urls import reverse

from ui import services
from ui.tests import Ui3TestCase


class UserManageTests(Ui3TestCase):
    def _staff(self, superuser=False):
        self.user.is_staff = True
        self.user.is_superuser = superuser
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.login()

    def _pending(self, username="newbie"):
        user = User.objects.create_user(username, password="hunter2")
        user.is_active = False
        user.save(update_fields=["is_active"])
        return user

    def test_non_staff_forbidden(self):
        pending = self._pending()
        self.login()
        response = self.client.get(reverse("ui3:users"))
        self.assertEqual(response.status_code, 403)
        create = self.client.post(
            reverse("ui3:user_create"),
            {"username": "eve", "password": "hunter2", "password_2": "hunter2", "activate": "1"},
        )
        self.assertEqual(create.status_code, 403)
        self.assertFalse(User.objects.filter(username="eve").exists())
        activate = self.client.post(reverse("ui3:user_activate", args=[pending.id]), {"active": "1"})
        self.assertEqual(activate.status_code, 403)
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)
        staff = self.client.post(reverse("ui3:user_staff", args=[self.other.id]), {"staff": "1"})
        self.assertEqual(staff.status_code, 403)
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_staff)
        htmx = self.client.post(
            reverse("ui3:user_activate", args=[pending.id]),
            {"active": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(htmx.status_code, 403)
        self.assertEqual(htmx["HX-Retarget"], "#toast-root")
        self.assertNotContains(self.client.get(reverse("ui3:jobs")), reverse("ui3:users"), status_code=200)
        page = self.client.get(reverse("ui3:account"))
        self.assertNotContains(page, reverse("ui3:users"))

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(reverse("ui3:users"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ui/login/", response["Location"])
        post = self.client.post(reverse("ui3:user_create"), {"username": "eve", "password": "x", "password_2": "x"})
        self.assertEqual(post.status_code, 302)
        self.assertIn("/ui/login/", post["Location"])

    def test_staff_can_open_and_see_nav(self):
        pending = self._pending()
        self._staff()
        response = self.client.get(reverse("ui3:users"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "newbie")
        self.assertContains(response, "Pending")
        self.assertContains(response, "Approve")
        self.assertContains(response, 'id="user-table"')
        self.assertContains(response, "1 pending")
        nav = self.client.get(reverse("ui3:jobs"))
        self.assertContains(nav, reverse("ui3:users"))
        self.assertContains(nav, "Users")
        account = self.client.get(reverse("ui3:account"))
        self.assertContains(account, reverse("ui3:users"))
        self.assertFalse(pending.is_active)

    def test_approve_pending_registration(self):
        pending = self._pending()
        self._staff()
        response = self.client.post(reverse("ui3:user_activate", args=[pending.id]), {"active": "1"})
        self.assertEqual(response.status_code, 302)
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.client.logout()
        self.assertTrue(self.client.login(username="newbie", password="hunter2"))

    def test_deactivate_is_not_pending(self):
        self._staff()
        response = self.client.post(reverse("ui3:user_activate", args=[self.other.id]), {"active": "0"})
        self.assertEqual(response.status_code, 302)
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_active)
        self.assertIsNotNone(self.other.last_login)
        pending_only = self.client.get(reverse("ui3:users"), {"state": "pending"})
        self.assertNotContains(pending_only, "<td>bob</td>")
        self.assertNotContains(pending_only, "1 pending")
        deactivated = self.client.get(reverse("ui3:users"), {"state": "deactivated"})
        self.assertContains(deactivated, "<td>bob</td>")
        self.assertContains(deactivated, "Deactivated")
        self.assertContains(deactivated, "Reactivate")
        self.client.logout()
        login = self.client.post(reverse("ui3:login"), {"username": "bob", "password": "secret"})
        self.assertContains(login, "This account has been deactivated.")

    def test_cannot_deactivate_self(self):
        self._staff()
        response = self.client.post(
            reverse("ui3:user_activate", args=[self.user.id]),
            {"active": "0"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["HX-Retarget"], "#toast-root")
        self.assertContains(response, "cannot deactivate your own account", status_code=400)
        self.assertNotContains(response, "<html", status_code=400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_cannot_revoke_own_staff(self):
        self._staff(superuser=True)
        response = self.client.post(
            reverse("ui3:user_staff", args=[self.user.id]),
            {"staff": "0"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["HX-Retarget"], "#toast-root")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)

    def test_non_superuser_cannot_change_superuser_or_grant_staff(self):
        admin = User.objects.create_user("root", password="secret", is_staff=True, is_superuser=True)
        self._staff()
        deactivate = self.client.post(reverse("ui3:user_activate", args=[admin.id]), {"active": "0"})
        self.assertEqual(deactivate.status_code, 302)
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)
        page = self.client.get(reverse("ui3:users"))
        self.assertNotContains(page, "Make staff")
        promoted = self.client.post(reverse("ui3:user_staff", args=[self.other.id]), {"staff": "1"})
        self.assertEqual(promoted.status_code, 302)
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_staff)
        created = self.client.post(
            reverse("ui3:user_create"),
            {
                "username": "staffed",
                "password": "hunter2",
                "password_2": "hunter2",
                "activate": "1",
                "staff": "1",
            },
        )
        self.assertEqual(created.status_code, 302)
        self.assertFalse(User.objects.filter(username="staffed").exists())

    def test_search_and_pending_filter(self):
        pending = User.objects.create_user("wait-one", password="hunter2", email="w@example.com")
        pending.is_active = False
        pending.save(update_fields=["is_active"])
        self._staff()
        found = self.client.get(reverse("ui3:users"), {"q": "wait-one"})
        self.assertContains(found, "wait-one")
        self.assertNotContains(found, "<td>alice</td>")
        pending_only = self.client.get(reverse("ui3:users"), {"state": "pending"})
        self.assertContains(pending_only, "wait-one")
        self.assertNotContains(pending_only, "<td>alice</td>")
        active_only = self.client.get(reverse("ui3:users"), {"state": "active"})
        self.assertContains(active_only, "<td>alice</td>")
        self.assertNotContains(active_only, "wait-one")
        staff_only = self.client.get(reverse("ui3:users"), {"state": "staff"})
        self.assertContains(staff_only, "<td>alice</td>")
        self.assertNotContains(staff_only, "<td>bob</td>")

    def test_create_and_superuser_toggle_staff(self):
        self._staff(superuser=True)
        created = self.client.post(
            reverse("ui3:user_create"),
            {
                "username": "cara",
                "email": "c@example.com",
                "password": "hunter2",
                "password_2": "hunter2",
                "activate": "1",
            },
        )
        self.assertEqual(created.status_code, 302)
        cara = User.objects.get(username="cara")
        self.assertTrue(cara.is_active)
        self.assertFalse(cara.is_staff)
        self.assertTrue(cara.groups.filter(name="normal").exists())
        page = self.client.get(reverse("ui3:users"))
        self.assertContains(page, "Make staff")
        promoted = self.client.post(reverse("ui3:user_staff", args=[cara.id]), {"staff": "1"})
        self.assertEqual(promoted.status_code, 302)
        cara.refresh_from_db()
        self.assertTrue(cara.is_staff)

    def test_create_validation_and_pending_default(self):
        self._staff()
        mismatch = self.client.post(
            reverse("ui3:user_create"),
            {"username": "cara", "password": "hunter2", "password_2": "nope"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(mismatch["HX-Retarget"], "#toast-root")
        self.assertFalse(User.objects.filter(username="cara").exists())
        duplicate = self.client.post(
            reverse("ui3:user_create"),
            {"username": "alice", "password": "hunter2", "password_2": "hunter2"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(duplicate.status_code, 400)
        created = self.client.post(
            reverse("ui3:user_create"),
            {"username": "cara", "password": "hunter2", "password_2": "hunter2"},
        )
        self.assertEqual(created.status_code, 302)
        cara = User.objects.get(username="cara")
        self.assertFalse(cara.is_active)
        self.assertIsNone(cara.last_login)
        pending = self.client.get(reverse("ui3:users"), {"state": "pending"})
        self.assertContains(pending, "<td>cara</td>")

    def test_missing_flag_does_not_grant(self):
        pending = self._pending()
        self._staff(superuser=True)
        activate = self.client.post(reverse("ui3:user_activate", args=[pending.id]), {})
        self.assertEqual(activate.status_code, 302)
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)
        staff = self.client.post(reverse("ui3:user_staff", args=[self.other.id]), {})
        self.assertEqual(staff.status_code, 302)
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_staff)

    def test_htmx_approve_returns_table(self):
        pending = self._pending("htmx-new")
        self._staff()
        listing = self.client.get(reverse("ui3:users"), HTTP_HX_REQUEST="true")
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, 'id="user-table"')
        self.assertNotContains(listing, "<html")
        response = self.client.post(
            reverse("ui3:user_activate", args=[pending.id]),
            {"active": "1"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="http://testserver/ui/users/?state=pending",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="user-table"')
        self.assertContains(response, "hx-swap=\"outerHTML\"")
        self.assertContains(response, "Approved")
        self.assertNotContains(response, "<html")
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)

    def test_last_staff_guard(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        bob = self.other
        bob.is_staff = True
        bob.save(update_fields=["is_staff"])
        User.objects.filter(pk=self.user.pk).update(is_staff=False)
        actor = User.objects.get(pk=self.user.pk)
        actor.is_staff = True
        with self.assertRaisesMessage(services.UserManageError, "last active staff"):
            services.set_user_active(actor, bob, False)
        bob.refresh_from_db()
        self.assertTrue(bob.is_active)
        actor.is_superuser = True
        with self.assertRaisesMessage(services.UserManageError, "last active staff"):
            services.set_user_staff(actor, bob, False)
        bob.refresh_from_db()
        self.assertTrue(bob.is_staff)
