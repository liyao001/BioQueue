from django.test import TestCase
from django.urls import reverse

from ui.tests import Ui3TestCase


class AuthTests(Ui3TestCase):
    def test_root_redirects_to_ui(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/ui/")

    def test_old_ui3_prefix_redirects(self):
        response = self.client.get("/ui3/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/ui/login/")

    def test_jobs_requires_login(self):
        response = self.client.get(reverse("ui3:jobs"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ui/login/", response["Location"])

    def test_htmx_unauthenticated_redirects_via_header(self):
        response = self.client.get(reverse("ui3:jobs"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response["HX-Redirect"].startswith("/ui/login/"))
        self.assertIn("next=", response["HX-Redirect"])

    def test_login_page_matches_app_chrome(self):
        response = self.client.get(reverse("ui3:login"))
        self.assertContains(response, "bq-header")
        self.assertContains(response, 'class="bq-logo"')
        self.assertContains(response, "ui3/logo.png")
        self.assertContains(response, "login-body")
        self.assertContains(response, "login-page")
        self.assertContains(response, "page-head")
        self.assertContains(response, "ui-input")
        self.assertContains(response, "ui-btn-primary")
        self.assertNotContains(response, 'id="bq-nav"')
        self.assertNotContains(response, "btn btn-primary")
        self.assertContains(response, reverse("ui3:register"))
        self.assertContains(response, "Create an account")

    def test_login_success(self):
        response = self.client.post(
            reverse("ui3:login"),
            {"username": "alice", "password": "secret"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/ui/jobs/")

    def test_login_failure(self):
        response = self.client.post(
            reverse("ui3:login"),
            {"username": "alice", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password")

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.post(
            reverse("ui3:login"),
            {"username": "alice", "password": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "waiting for administrator approval")
        wrong = self.client.post(
            reverse("ui3:login"),
            {"username": "alice", "password": "wrong"},
        )
        self.assertContains(wrong, "Invalid username or password")

    def test_logout_rejects_get(self):
        self.login()
        response = self.client.get(reverse("ui3:logout"))
        self.assertEqual(response.status_code, 405)

    def test_views_package_does_not_import_siblings(self):
        import inspect

        import ui.views

        source = inspect.getsource(ui.views)
        self.assertNotIn("from .jobs", source)
        self.assertNotIn("from .environments", source)
        self.assertNotIn("from .workspaces", source)

    def test_next_must_stay_inside_ui3(self):
        response = self.client.post(
            reverse("ui3:login"),
            {"username": "alice", "password": "secret", "next": "https://evil.example/"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/ui/jobs/")


class RegisterTests(Ui3TestCase):
    def test_register_page(self):
        response = self.client.get(reverse("ui3:register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create an account")
        self.assertContains(response, "login-body")
        self.assertContains(response, "ui-input")
        self.assertContains(response, "ui-btn-primary")
        self.assertNotContains(response, 'id="bq-nav"')

    def test_register_creates_inactive_user(self):
        from django.contrib.auth.models import User

        response = self.client.post(
            reverse("ui3:register"),
            {
                "username": "newbie",
                "email": "n@example.com",
                "first_name": "New",
                "last_name": "Bee",
                "password": "hunter2",
                "password_2": "hunter2",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ui/login/", response["Location"])
        user = User.objects.get(username="newbie")
        self.assertFalse(user.is_active)
        login = self.client.post(reverse("ui3:login"), {"username": "newbie", "password": "hunter2"})
        self.assertEqual(login.status_code, 200)
        self.assertContains(login, "waiting for administrator approval")

    def test_deactivated_user_login_message(self):
        from django.contrib.auth.models import User
        from django.utils import timezone

        user = User.objects.create_user("oldie", password="hunter2")
        user.is_active = False
        user.last_login = timezone.now()
        user.save(update_fields=["is_active", "last_login"])
        login = self.client.post(reverse("ui3:login"), {"username": "oldie", "password": "hunter2"})
        self.assertEqual(login.status_code, 200)
        self.assertContains(login, "This account has been deactivated.")
        wrong = self.client.post(reverse("ui3:login"), {"username": "oldie", "password": "wrong"})
        self.assertContains(wrong, "Invalid username or password")

    def test_register_rejects_duplicate_username(self):
        response = self.client.post(
            reverse("ui3:register"),
            {"username": "alice", "password": "x", "password_2": "x"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already taken")

    def test_register_rejects_password_mismatch(self):
        response = self.client.post(
            reverse("ui3:register"),
            {"username": "otheruser", "password": "one", "password_2": "two"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "do not match")

    def test_register_rejects_invalid_username(self):
        from django.contrib.auth.models import User

        response = self.client.post(
            reverse("ui3:register"),
            {"username": "bad user!", "password": "hunter2", "password_2": "hunter2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="bad user!").exists())

    def test_authenticated_user_is_redirected_from_register(self):
        self.login()
        response = self.client.get(reverse("ui3:register"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/ui/jobs/")


class AccountTests(Ui3TestCase):
    def test_account_requires_login(self):
        response = self.client.get(reverse("ui3:account"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ui/login/", response["Location"])

    def test_account_page_shows_folder_defaults(self):
        self.login()
        response = self.client.get(reverse("ui3:account"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Change password")
        self.assertContains(response, "Folder paths")
        self.assertContains(response, "Workspace")
        self.assertContains(response, "Uploads")
        self.assertContains(response, "Bin")
        self.assertContains(response, reverse("ui3:clean_folders"))

    def test_change_password(self):
        self.login()
        bad = self.client.post(
            reverse("ui3:account"),
            {"section": "password", "old_password": "nope", "new_password": "newpass", "new_password_2": "newpass"},
        )
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, "Current password is incorrect")
        mismatch = self.client.post(
            reverse("ui3:account"),
            {"section": "password", "old_password": "secret", "new_password": "aaa", "new_password_2": "bbb"},
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertContains(mismatch, "do not match")
        ok = self.client.post(
            reverse("ui3:account"),
            {"section": "password", "old_password": "secret", "new_password": "newpass", "new_password_2": "newpass"},
        )
        self.assertEqual(ok.status_code, 302)
        self.client.logout()
        self.assertTrue(self.client.login(username="alice", password="newpass"))

    def test_update_folder_paths(self):
        self.login()
        response = self.client.post(
            reverse("ui3:account"),
            {"section": "folders", "upload_folder": "/tmp/uploads", "archive_folder": "/tmp/archives"},
        )
        self.assertEqual(response.status_code, 302)
        profile = self.user.queuedb_profile_related
        profile.refresh_from_db()
        self.assertEqual(profile.upload_folder, "/tmp/uploads")
        self.assertEqual(profile.archive_folder, "/tmp/archives")
        page = self.client.get(reverse("ui3:account"))
        self.assertContains(page, "/tmp/uploads")
        self.assertContains(page, "/tmp/archives")

    def test_folder_path_too_long(self):
        self.login()
        response = self.client.post(
            reverse("ui3:account"),
            {"section": "folders", "upload_folder": "x" * 1025, "archive_folder": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "too long")

    def test_clean_unlinked_folders(self):
        import os
        import shutil
        import tempfile
        from unittest.mock import patch

        tmp = tempfile.mkdtemp()
        try:
            root = os.path.join(tmp, str(self.user.id))
            os.makedirs(os.path.join(root, "uploads"))
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "dead-run"))
            with open(os.path.join(root, "dead-run", "x.txt"), "w") as fh:
                fh.write("x")
            self.make_job(result="live-out")
            os.makedirs(os.path.join(root, "live-out"))
            self.login()
            with patch("ui.files.configured_workspace_base", return_value=tmp):
                response = self.client.post(reverse("ui3:clean_folders"))
            self.assertEqual(response.status_code, 302)
            self.assertFalse(os.path.isdir(os.path.join(root, "dead-run")))
            self.assertTrue(os.path.isdir(os.path.join(root, "uploads")))
            self.assertTrue(os.path.isdir(os.path.join(root, "bin")))
            self.assertTrue(os.path.isdir(os.path.join(root, "live-out")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_clean_refuses_without_workspace_config(self):
        from unittest.mock import patch

        self.login()
        with patch("ui.files.configured_workspace_base", return_value=None):
            response = self.client.post(reverse("ui3:clean_folders"), follow=True)
        self.assertContains(response, "not configured")

    def test_nav_includes_account_and_archives(self):
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, reverse("ui3:account"))
        self.assertContains(response, reverse("ui3:archives"))
