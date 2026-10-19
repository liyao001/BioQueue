"""Notification hook validation, delivery, and the notifications page."""

import hashlib
import hmac
import json
import urllib.request
from unittest.mock import patch

from django.urls import reverse

from QueueDB.models import NotificationHook
from QueueDB.notifications import (
    NotificationError,
    _send,
    build_notice,
    deliver,
    notify_job,
    save_hook_fields,
)
from ui.tests import Ui3TestCase


class _Post(dict):
    def getlist(self, key):
        value = self.get(key, [])
        if isinstance(value, (list, tuple)):
            return list(value)
        if value in ("", None):
            return []
        return [value]


def _notice(event="finished"):
    return {
        "event": event,
        "job_id": 9,
        "job_name": "align",
        "protocol": "RNA-seq",
        "workspace": "ws1",
        "user_id": 1,
    }


class _Capture:
    def __init__(self):
        self.request = None
        self.label = None

    def __call__(self, request, label, secrets=()):
        self.request = request
        self.label = label


def _hook(user, provider, config, events="finished,failed,interrupted", name="lab"):
    return NotificationHook.objects.create(
        user=user,
        name=name,
        provider=provider,
        enabled=1,
        events=events,
        config=json.dumps(config),
    )


class DeliveryTests(Ui3TestCase):
    def test_discord_payload_disables_mentions(self):
        hook = _hook(self.user, "discord", {"webhook_url": "https://discord.com/api/webhooks/1/abc"})
        seen = _Capture()
        with patch("QueueDB.notifications._send", seen):
            deliver(hook, _notice())
        body = json.loads(seen.request.data.decode("utf-8"))
        self.assertEqual(seen.request.full_url, "https://discord.com/api/webhooks/1/abc")
        self.assertIn("align (#9) finished", body["content"])
        self.assertIn("RNA-seq", body["content"])
        self.assertEqual(body["allowed_mentions"], {"parse": []})

    def test_telegram_posts_to_bot_api(self):
        hook = _hook(self.user, "telegram", {"bot_token": "123:ABC_def", "chat_id": "-1005"})
        seen = _Capture()
        with patch("QueueDB.notifications._send", seen):
            deliver(hook, _notice("failed"))
        self.assertEqual(seen.request.full_url, "https://api.telegram.org/bot123:ABC_def/sendMessage")
        body = json.loads(seen.request.data.decode("utf-8"))
        self.assertEqual(body["chat_id"], "-1005")
        self.assertIn("failed", body["text"])

    def test_slack_and_mattermost_send_text(self):
        for provider, url in (
            ("slack", "https://hooks.slack.com/services/T/B/X"),
            ("mattermost", "https://chat.example/hooks/abc"),
        ):
            hook = _hook(self.user, provider, {"webhook_url": url}, name=provider)
            seen = _Capture()
            with patch("QueueDB.notifications._send", seen):
                deliver(hook, _notice())
            self.assertEqual(json.loads(seen.request.data.decode("utf-8"))["text"][:8], "BioQueue")
            self.assertEqual(seen.request.full_url, url)

    def test_teams_message_card(self):
        hook = _hook(self.user, "teams", {"webhook_url": "https://example.webhook.office.com/hook"})
        seen = _Capture()
        with patch("QueueDB.notifications._send", seen):
            deliver(hook, _notice("failed"))
        body = json.loads(seen.request.data.decode("utf-8"))
        self.assertEqual(body["@type"], "MessageCard")
        self.assertEqual(body["themeColor"], "D9534F")

    def test_webhook_signs_body(self):
        hook = _hook(self.user, "webhook", {"url": "https://example.com/hook", "secret": "topsecret"})
        seen = _Capture()
        with patch("QueueDB.notifications._send", seen):
            deliver(hook, _notice())
        raw = seen.request.data
        digest = hmac.new(b"topsecret", raw, hashlib.sha256).hexdigest()
        self.assertEqual(seen.request.get_header("X-bioqueue-signature"), "sha256=" + digest)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["event"], "finished")
        self.assertEqual(payload["job_id"], 9)

    def test_ntfy_sets_title_and_priority(self):
        hook = _hook(self.user, "ntfy", {"url": "https://ntfy.sh/lab", "token": "tk_secret"})
        seen = _Capture()
        with patch("QueueDB.notifications._send", seen):
            deliver(hook, _notice("failed"))
        self.assertEqual(seen.request.get_header("Priority"), "5")
        self.assertEqual(seen.request.get_header("Title")[:8], "BioQueue")
        self.assertEqual(seen.request.get_header("Authorization"), "Bearer tk_secret")
        self.assertNotIn("tk_secret", seen.request.full_url)

    def test_gotify_uses_header_token(self):
        hook = _hook(self.user, "gotify", {"url": "https://gotify.example", "token": "app-token"})
        seen = _Capture()
        with patch("QueueDB.notifications._send", seen):
            deliver(hook, _notice())
        self.assertEqual(seen.request.full_url, "https://gotify.example/message")
        self.assertEqual(seen.request.get_header("X-gotify-key"), "app-token")

    def test_pushover_form_posts_to_api(self):
        hook = _hook(self.user, "pushover", {"user_key": "u" * 12, "api_token": "a" * 12})
        seen = _Capture()
        with patch("QueueDB.notifications._send", seen):
            deliver(hook, _notice("failed"))
        self.assertEqual(seen.request.full_url, "https://api.pushover.net/1/messages.json")
        body = seen.request.data.decode("utf-8")
        self.assertIn("priority=1", body)
        self.assertIn("token=" + ("a" * 12), body)

    def test_email_uses_hook_smtp(self):
        hook = _hook(
            self.user,
            "email",
            {
                "to": "you@example.com",
                "smtp_host": "smtp.example.com",
                "smtp_port": "2525",
                "smtp_user": "mailer",
                "smtp_password": "secret",
                "smtp_security": "none",
            },
        )
        with patch("QueueDB.notifications.smtplib.SMTP") as smtp:
            deliver(hook, _notice())
        smtp.assert_called_with("smtp.example.com", 2525, timeout=8)
        client = smtp.return_value
        client.login.assert_called_with("mailer", "secret")
        client.send_message.assert_called()
        client.starttls.assert_not_called()

    def test_email_falls_back_to_site_mail(self):
        hook = _hook(self.user, "email", {"to": "you@example.com"})
        site = {
            "mail_host": "smtp.lab",
            "mail_port": "587",
            "mail_user": "bot",
            "mail_password": "pw",
            "sender": "bot@lab",
        }
        with patch("QueueDB.notifications.load_site_mail", return_value=site), patch(
            "QueueDB.notifications.smtplib.SMTP"
        ) as smtp:
            deliver(hook, _notice())
        smtp.assert_called_with("smtp.lab", 587, timeout=8)
        smtp.return_value.starttls.assert_called()
        sent = smtp.return_value.send_message.call_args.args[0]
        self.assertEqual(sent["To"], "you@example.com")
        self.assertEqual(sent["From"], "bot@lab")

    def test_redirect_is_not_followed(self):
        class _Resp:
            status = 302

            def read(self, _n):
                return b""

            def getcode(self):
                return 302

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("QueueDB.notifications.urllib.request.build_opener") as build:
            build.return_value.open.return_value = _Resp()
            with self.assertRaises(NotificationError) as caught:
                _send(urllib.request.Request("https://example.com/hook"), "Discord")
        self.assertIn("HTTP 302", str(caught.exception))

    def test_notify_respects_events_and_enabled(self):
        _hook(self.user, "discord", {"webhook_url": "https://discord.com/api/webhooks/1/abc"}, events="failed")
        _hook(
            self.user,
            "slack",
            {"webhook_url": "https://hooks.slack.com/services/T/B/X"},
            events="finished",
            name="off",
        )
        NotificationHook.objects.filter(name="off").update(enabled=0)
        job = self.make_job(job_name="align")
        with patch("QueueDB.notifications.deliver") as send:
            notify_job(job, "finished", background=False)
            send.assert_not_called()
            notify_job(job, "failed", background=False)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0].provider, "discord")
        self.assertEqual(send.call_args.args[1]["job_name"], "align")

    def test_build_notice_includes_protocol(self):
        job = self.make_job(job_name="align", workspace=self.workspace)
        notice = build_notice(job, "finished")
        self.assertEqual(notice["protocol"], "RNA-seq")
        self.assertEqual(notice["workspace"], "ws1")


class ValidationTests(Ui3TestCase):
    def _post(self, **extra):
        data = {
            "name": "Lab",
            "provider": "discord",
            "enabled": "1",
            "events": ["finished", "failed"],
            "webhook_url": "https://discord.com/api/webhooks/9/token",
        }
        data.update(extra)
        return _Post(data)

    def test_rejects_non_discord_url(self):
        with self.assertRaises(NotificationError):
            save_hook_fields(self._post(webhook_url="https://evil.example/api/webhooks/1/x"))

    def test_blank_secret_keeps_saved_value(self):
        hook = _hook(self.user, "discord", {"webhook_url": "https://discord.com/api/webhooks/9/token"})
        fields = save_hook_fields(self._post(webhook_url="", name="Renamed"), existing=hook)
        self.assertEqual(fields["name"], "Renamed")
        self.assertIn("token", fields["config"])

    def test_requires_an_event(self):
        with self.assertRaises(NotificationError):
            save_hook_fields(self._post(events=[]))


class NotificationPageTests(Ui3TestCase):
    def test_page_lists_services(self):
        self.login()
        response = self.client.get(reverse("ui3:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Discord")
        self.assertContains(response, "Telegram")
        self.assertContains(response, "Generic webhook")
        self.assertContains(response, "id=\"notification-table\"")

    def test_anonymous_redirects(self):
        response = self.client.get(reverse("ui3:notifications"))
        self.assertEqual(response.status_code, 302)

    def test_create_lists_hook_without_secret(self):
        self.login()
        response = self.client.post(
            reverse("ui3:notification_create"),
            {
                "name": "Lab Discord",
                "provider": "discord",
                "enabled": "1",
                "events": ["finished", "failed", "interrupted"],
                "webhook_url": "https://discord.com/api/webhooks/9/supersecret",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Lab Discord")
        self.assertNotContains(response, "supersecret")
        hook = NotificationHook.objects.get(name="Lab Discord")
        self.assertEqual(hook.user_id, self.user.id)
        self.assertEqual(json.loads(hook.config)["webhook_url"].rsplit("/", 1)[-1], "supersecret")

    def test_create_rejects_bad_input(self):
        self.login()
        response = self.client.post(
            reverse("ui3:notification_create"),
            {"name": "x", "provider": "nope", "enabled": "1", "events": ["finished"]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Choose a notification service", status_code=400)

    def test_other_user_cannot_edit(self):
        hook = _hook(self.user, "discord", {"webhook_url": "https://discord.com/api/webhooks/1/abc"})
        self.login("bob")
        response = self.client.get(reverse("ui3:notification_edit", args=[hook.id]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse("ui3:notification_delete", args=[hook.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(NotificationHook.objects.filter(id=hook.id).exists())

    def test_fields_partial_follows_provider(self):
        self.login()
        response = self.client.get(reverse("ui3:notification_fields"), {"provider": "telegram"})
        self.assertContains(response, "Bot token")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, "Webhook URL")

    def test_edit_keeps_secret_and_test_sends(self):
        hook = _hook(self.user, "discord", {"webhook_url": "https://discord.com/api/webhooks/9/token"})
        self.login()
        response = self.client.post(
            reverse("ui3:notification_edit", args=[hook.id]),
            {
                "name": "Renamed",
                "provider": "discord",
                "enabled": "1",
                "events": ["finished"],
                "webhook_url": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        hook.refresh_from_db()
        self.assertEqual(hook.name, "Renamed")
        self.assertIn("token", hook.config)
        with patch("ui.views.notifications.deliver") as send:
            tested = self.client.post(
                reverse("ui3:notification_test", args=[hook.id]),
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(tested.status_code, 200)
        self.assertContains(tested, "Test message sent")
        send.assert_called_once()

    def test_delete(self):
        hook = _hook(self.user, "ntfy", {"url": "https://ntfy.sh/lab"})
        self.login()
        response = self.client.post(
            reverse("ui3:notification_delete", args=[hook.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(NotificationHook.objects.filter(id=hook.id).exists())
        self.assertContains(response, "No notification hooks yet")
