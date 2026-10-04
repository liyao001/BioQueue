"""User notification hooks for job status changes.

The worker calls :func:`notify_job` when a job starts, finishes, fails, or is
interrupted. Delivery is best-effort: a slow or failing endpoint is logged and
does not change the job.

Hook configuration is JSON on ``NotificationHook.config``. Tokens stay in the
database and are not written to the worker log.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import smtplib
import threading
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from django.db import close_old_connections

logger = logging.getLogger("BioQueue.notify")

TIMEOUT = 8
MAX_HOOKS = 30
MAX_MESSAGE = 1800
USER_AGENT = "BioQueue"

EVENT_STARTED = "started"
EVENT_FINISHED = "finished"
EVENT_FAILED = "failed"
EVENT_INTERRUPTED = "interrupted"
EVENT_KEYS = (EVENT_STARTED, EVENT_FINISHED, EVENT_FAILED, EVENT_INTERRUPTED)
DEFAULT_EVENTS = (EVENT_FINISHED, EVENT_FAILED, EVENT_INTERRUPTED)
EVENT_LABELS = {
    EVENT_STARTED: "Started",
    EVENT_FINISHED: "Finished",
    EVENT_FAILED: "Failed",
    EVENT_INTERRUPTED: "Interrupted",
}


class NotificationError(Exception):
    """A hook could not be saved or delivered. The message is safe to show."""


def _field(name, label, *, secret=False, required=True, placeholder="", mono=False, choices=None, input_type=None):
    if input_type is None:
        input_type = "password" if secret else "text"
    return {
        "name": name,
        "label": label,
        "secret": secret,
        "required": required,
        "placeholder": placeholder,
        "mono": mono,
        "choices": choices,
        "input": input_type,
    }


_SMTP_SECURITY = (
    ("", "Default (STARTTLS on port 587)"),
    ("starttls", "STARTTLS"),
    ("ssl", "SSL / TLS"),
    ("none", "None"),
)

PROVIDERS = {
    "discord": {
        "label": "Discord",
        "help": "Channel menu → Integrations → Webhooks → New Webhook, then copy the webhook URL.",
        "fields": [
            _field(
                "webhook_url",
                "Webhook URL",
                secret=True,
                placeholder="https://discord.com/api/webhooks/…",
                mono=True,
            ),
        ],
    },
    "telegram": {
        "label": "Telegram",
        "help": "Create a bot with @BotFather, send it a message, then use that chat id. Group ids are negative numbers.",
        "fields": [
            _field("bot_token", "Bot token", secret=True, placeholder="123456789:AA…", mono=True),
            _field("chat_id", "Chat ID", placeholder="-1001234567890 or 123456789", mono=True),
        ],
    },
    "slack": {
        "label": "Slack",
        "help": "Create an incoming webhook for a channel and paste the hooks.slack.com URL.",
        "fields": [
            _field(
                "webhook_url",
                "Webhook URL",
                secret=True,
                placeholder="https://hooks.slack.com/services/…",
                mono=True,
            ),
        ],
    },
    "teams": {
        "label": "Microsoft Teams",
        "help": "Incoming webhook URL for a channel (Office 365 connector or a Workflows webhook that accepts a MessageCard).",
        "fields": [
            _field("webhook_url", "Webhook URL", secret=True, placeholder="https://…", mono=True),
        ],
    },
    "mattermost": {
        "label": "Mattermost",
        "help": "Incoming webhook URL from Integrations → Incoming Webhooks.",
        "fields": [
            _field("webhook_url", "Webhook URL", secret=True, placeholder="https://mattermost.example/hooks/…", mono=True),
        ],
    },
    "ntfy": {
        "label": "ntfy",
        "help": "Topic URL, for example https://ntfy.sh/your-private-topic. Add an access token if the topic is protected.",
        "fields": [
            _field("url", "Topic URL", placeholder="https://ntfy.sh/bioqueue-lab", mono=True),
            _field("token", "Access token", secret=True, required=False, placeholder="tk_…", mono=True),
        ],
    },
    "gotify": {
        "label": "Gotify",
        "help": "Server URL and an application token from Gotify → Apps.",
        "fields": [
            _field("url", "Server URL", placeholder="https://gotify.example", mono=True),
            _field("token", "Application token", secret=True, mono=True),
        ],
    },
    "pushover": {
        "label": "Pushover",
        "help": "Your user key and an application API token from pushover.net.",
        "fields": [
            _field("user_key", "User key", mono=True),
            _field("api_token", "API token", secret=True, mono=True),
        ],
    },
    "email": {
        "label": "Email",
        "help": "Sends through the SMTP server in config/custom.conf under [mail], or the SMTP fields on this hook.",
        "fields": [
            _field("to", "To", placeholder="you@example.com", input_type="email"),
            _field("sender", "From", required=False, placeholder="bioqueue@example.com"),
            _field("smtp_host", "SMTP host", required=False, placeholder="smtp.example.com", mono=True),
            _field("smtp_port", "SMTP port", required=False, placeholder="587", mono=True),
            _field("smtp_user", "SMTP user", required=False, mono=True),
            _field("smtp_password", "SMTP password", secret=True, required=False),
            _field("smtp_security", "Security", required=False, choices=_SMTP_SECURITY),
        ],
    },
    "webhook": {
        "label": "Generic webhook",
        "help": "POST JSON to any http(s) URL. If you set a signing secret, the request includes X-BioQueue-Signature: sha256=<hmac of the body>.",
        "fields": [
            _field("url", "URL", placeholder="https://example.com/bioqueue", mono=True),
            _field("secret", "Signing secret", secret=True, required=False, mono=True),
        ],
    },
}


def provider_label(key):
    spec = PROVIDERS.get(key or "")
    return spec["label"] if spec else (key or "")


def event_labels(events_csv):
    labels = []
    for key in str(events_csv or "").split(","):
        key = key.strip()
        if not key:
            continue
        labels.append(EVENT_LABELS.get(key, key))
    return ", ".join(labels)


def destination_summary(provider, config_text):
    """Short destination label that does not include secrets."""
    config = stored_config_text(config_text)
    if provider == "telegram":
        chat = config.get("chat_id") or ""
        return "chat {}".format(chat) if chat else "Telegram"
    if provider == "ntfy":
        return _host_of(config.get("url") or "") or "ntfy"
    if provider == "gotify":
        return _host_of(config.get("url") or "") or "Gotify"
    if provider == "pushover":
        key = config.get("user_key") or ""
        tail = key[-4:] if len(key) >= 4 else ""
        return "user …{}".format(tail) if tail else "Pushover"
    if provider == "email":
        return config.get("to") or "Email"
    if provider == "webhook":
        return _host_of(config.get("url") or "") or "Webhook"
    return provider_label(provider)


def provider_choices():
    return [{"key": key, "label": spec["label"]} for key, spec in PROVIDERS.items()]


def form_fields(provider, config=None, keep_secrets=False):
    """Copies of the provider fields with non-secret values filled in."""
    spec = PROVIDERS.get(provider)
    if spec is None:
        return []
    values = config or {}
    rows = []
    for field in spec["fields"]:
        row = dict(field)
        if field.get("secret"):
            row["value"] = ""
        else:
            row["value"] = values.get(field["name"], "") or ""
        row["keep"] = bool(keep_secrets and field.get("secret"))
        rows.append(row)
    return rows


def provider_help(provider):
    spec = PROVIDERS.get(provider)
    return spec["help"] if spec else ""


def stored_config_text(config_text):
    try:
        data = json.loads(config_text or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned = {}
    for key, value in data.items():
        if value is None:
            continue
        cleaned[str(key)] = str(value)
    return cleaned


def build_notice(job, event):
    protocol = ""
    workspace = ""
    try:
        if getattr(job, "protocol_id", None):
            protocol = job.protocol.name or ""
    except Exception:
        protocol = ""
    try:
        if getattr(job, "workspace_id", None):
            workspace = job.workspace.name or ""
    except Exception:
        workspace = ""
    return {
        "event": event,
        "job_id": getattr(job, "id", None),
        "job_name": getattr(job, "job_name", "") or "",
        "protocol": protocol,
        "workspace": workspace,
        "user_id": getattr(job, "user_id", None),
    }


def render_message(notice):
    custom = (notice.get("message") or "").strip()
    if custom:
        text = custom
    else:
        name = notice.get("job_name") or "job"
        job_id = notice.get("job_id")
        label = EVENT_LABELS.get(notice.get("event"), notice.get("event") or "updated").lower()
        lines = ["BioQueue: {} (#{}) {}.".format(name, job_id, label)]
        if notice.get("protocol"):
            lines.append("Protocol: {}".format(notice["protocol"]))
        if notice.get("workspace"):
            lines.append("Workspace: {}".format(notice["workspace"]))
        text = "\n".join(lines)
    if len(text) > MAX_MESSAGE:
        text = text[: MAX_MESSAGE - 3] + "..."
    return text


def render_title(notice):
    if notice.get("message") and not notice.get("job_id"):
        return "BioQueue test"
    name = notice.get("job_name") or "job"
    job_id = notice.get("job_id")
    label = EVENT_LABELS.get(notice.get("event"), "Updated")
    title = "BioQueue: {} (#{}) {}".format(name, job_id, label)
    return title.replace("\n", " ")[:200]


def sample_notice(hook):
    name = hook.name or "notification"
    return {
        "event": EVENT_FINISHED,
        "job_id": 0,
        "job_name": name,
        "protocol": "",
        "workspace": "",
        "user_id": hook.user_id,
        "message": 'BioQueue test: hook "{}" is working.'.format(name),
    }


def save_hook_fields(post, existing=None):
    """Validate a create or update submission. Raises NotificationError."""
    name = _clean_line(post.get("name"), "Name", 80)
    if not name:
        raise NotificationError("Name is required.")
    provider = (post.get("provider") or "").strip()
    if provider not in PROVIDERS:
        raise NotificationError("Choose a notification service.")
    enabled = (post.get("enabled") or "0").strip() == "1"
    events = _posted_events(post)
    if not events:
        raise NotificationError("Choose at least one event.")
    previous = {}
    if existing is not None and existing.provider == provider:
        previous = stored_config_text(existing.config)
    config = _collect_config(provider, post, previous)
    _validate_config(provider, config)
    return {
        "name": name,
        "provider": provider,
        "enabled": 1 if enabled else 0,
        "events": ",".join(events),
        "config": json.dumps(config, ensure_ascii=False, separators=(",", ":")),
    }


def notify_job(job, event, *, background=True, mail_settings=None):
    """Tell the job owner's enabled hooks about ``event``. Never raises."""
    if event not in EVENT_KEYS:
        return
    user_id = getattr(job, "user_id", None)
    if not user_id:
        return
    try:
        from QueueDB.models import NotificationHook

        if not NotificationHook.objects.filter(user_id=user_id, enabled=1).exists():
            return
    except Exception:
        logger.exception("Could not look up notification hooks for user %s", user_id)
        return
    notice = build_notice(job, event)
    mail = dict(mail_settings or {})
    if background:
        threading.Thread(
            target=_dispatch,
            args=(notice, mail),
            name="bioqueue-notify-{}".format(notice.get("job_id") or "job"),
            daemon=True,
        ).start()
        return
    _dispatch(notice, mail)


def deliver(hook, notice, mail_settings=None):
    """Send one hook. Raises NotificationError on failure."""
    spec = PROVIDERS.get(hook.provider)
    if spec is None:
        raise NotificationError("Unknown notification service.")
    config = stored_config_text(hook.config)
    message = render_message(notice)
    sender = _SENDERS.get(hook.provider)
    if sender is None:
        raise NotificationError("Unknown notification service.")
    sender(config, notice, message, mail_settings)


def load_site_mail():
    """``[mail]`` from custom.conf. Missing file or section yields ``{}``."""
    path = os.environ.get("BIOQUEUE_CUSTOM_CONF") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "custom.conf",
    )
    try:
        from configparser import ConfigParser

        parser = ConfigParser()
        parser.read(path)
        if not parser.has_section("mail"):
            return {}
        return {key: parser.get("mail", key) for key in parser.options("mail")}
    except Exception:
        logger.debug("Could not read mail settings from %s", path, exc_info=True)
        return {}


def _dispatch(notice, mail):
    close_old_connections()
    try:
        from QueueDB.models import NotificationHook

        hooks = list(NotificationHook.objects.filter(user_id=notice.get("user_id"), enabled=1))
        for hook in hooks:
            if notice.get("event") not in hook.event_keys():
                continue
            try:
                deliver(hook, notice, mail_settings=mail)
                logger.info(
                    "Sent %s notification for job %s via %s hook %s",
                    notice.get("event"),
                    notice.get("job_id"),
                    hook.provider,
                    hook.id,
                )
            except NotificationError as exc:
                logger.warning(
                    "Notification hook %s (%s) failed for job %s: %s",
                    hook.id,
                    hook.provider,
                    notice.get("job_id"),
                    exc,
                )
            except Exception:
                logger.exception(
                    "Notification hook %s (%s) failed for job %s",
                    hook.id,
                    hook.provider,
                    notice.get("job_id"),
                )
    except Exception:
        logger.exception("Notification dispatch failed for job %s", notice.get("job_id"))
    finally:
        close_old_connections()


def _posted_events(post):
    if hasattr(post, "getlist"):
        raw = post.getlist("events")
    else:
        raw = post.get("events")
    if raw is None:
        values = []
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = [raw]
    chosen = []
    for key in EVENT_KEYS:
        if key in values:
            chosen.append(key)
    return chosen


def _clean_line(value, label, limit):
    text = (value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        raise NotificationError("{} is too long (max {} characters).".format(label, limit))
    return text


def _collect_config(provider, post, previous):
    config = {}
    for field in PROVIDERS[provider]["fields"]:
        raw = post.get(field["name"])
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            raw = str(raw)
        raw = raw.replace("\r", "").replace("\n", "").strip()
        if raw == "" and field.get("secret") and previous.get(field["name"]):
            raw = previous[field["name"]]
        if field.get("required", True) and not raw:
            raise NotificationError("{} is required.".format(field["label"]))
        if len(raw) > 2000:
            raise NotificationError("{} is too long.".format(field["label"]))
        if raw:
            config[field["name"]] = raw
    return config


def _validate_config(provider, config):
    if provider == "discord":
        _webhook_url(config["webhook_url"], hosts=_DISCORD_HOSTS, path_part="/api/webhooks/", label="Discord webhook URL")
    elif provider == "slack":
        _webhook_url(config["webhook_url"], hosts=("hooks.slack.com",), path_part="/services/", label="Slack webhook URL")
    elif provider == "teams":
        _http_url(config["webhook_url"], https_only=True, label="Teams webhook URL")
    elif provider == "mattermost":
        _http_url(config["webhook_url"], label="Mattermost webhook URL")
    elif provider == "telegram":
        token = config["bot_token"]
        if not _TELEGRAM_TOKEN.match(token):
            raise NotificationError("Bot token should look like 123456789:AA….")
        chat = config["chat_id"]
        if not _TELEGRAM_CHAT.match(chat):
            raise NotificationError("Chat ID should be a number or an @channel name.")
    elif provider == "ntfy":
        _http_url(config["url"], label="Topic URL")
    elif provider == "gotify":
        _http_url(config["url"], label="Server URL")
    elif provider == "pushover":
        if len(config.get("user_key") or "") < 8 or len(config.get("api_token") or "") < 8:
            raise NotificationError("Pushover user key and API token look too short.")
    elif provider == "email":
        if not _email_ok(config.get("to") or ""):
            raise NotificationError("Enter a single recipient email address.")
        sender = config.get("sender") or ""
        if sender and not _email_ok(sender):
            raise NotificationError("From address is not a valid email.")
        port = config.get("smtp_port") or ""
        if port:
            try:
                number = int(port)
            except ValueError:
                number = 0
            if number < 1 or number > 65535:
                raise NotificationError("SMTP port must be between 1 and 65535.")
        security = config.get("smtp_security") or ""
        if security not in ("", "starttls", "ssl", "none"):
            raise NotificationError("Choose a valid SMTP security option.")
    elif provider == "webhook":
        _http_url(config["url"], label="Webhook URL")


_DISCORD_HOSTS = ("discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com")

_TELEGRAM_TOKEN = re.compile(r"^[0-9]+:[A-Za-z0-9_-]+$")
_TELEGRAM_CHAT = re.compile(r"^(-?[0-9]{1,20}|@[A-Za-z][A-Za-z0-9_]{4,})$")


def _http_url(value, *, https_only=False, label="URL"):
    if any(char in value for char in " \t\r\n\x00"):
        raise NotificationError("{} cannot contain spaces.".format(label))
    parsed = urllib.parse.urlparse(value)
    schemes = ("https",) if https_only else ("http", "https")
    host = parsed.hostname or ""
    if parsed.scheme not in schemes or not host or parsed.username or parsed.password:
        expected = "https://" if https_only else "http:// or https://"
        raise NotificationError("{} must be an {} address.".format(label, expected))
    return value


def _webhook_url(value, *, hosts, path_part, label):
    _http_url(value, https_only=True, label=label)
    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    if host not in hosts and not any(host.endswith("." + item) for item in hosts):
        raise NotificationError("{} must be on {}.".format(label, " or ".join(hosts)))
    if path_part not in (parsed.path or ""):
        raise NotificationError("{} is not a webhook URL.".format(label))
    return value


def _email_ok(value):
    if not value or len(value) > 254 or any(char.isspace() for char in value):
        return False
    if value.count("@") != 1:
        return False
    local, domain = value.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def _host_of(url):
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send(request, label, secrets=()):
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            response.read(2048)
            status = getattr(response, "status", None) or response.getcode()
    except NotificationError:
        raise
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(300).decode("utf-8", "replace")
        except Exception:
            detail = ""
        detail = _redact(detail, secrets)
        raise NotificationError("{} returned HTTP {}{}.".format(label, exc.code, ": " + detail if detail else ""))
    except urllib.error.URLError as exc:
        reason = _redact(str(getattr(exc, "reason", exc)), secrets)
        raise NotificationError("Could not reach {} ({}).".format(label, reason))
    except Exception as exc:
        raise NotificationError("Could not reach {} ({}).".format(label, _redact(str(exc), secrets)))
    if status is None or status >= 300:
        raise NotificationError("{} returned HTTP {}.".format(label, status))


def _redact(text, secrets):
    cleaned = " ".join((text or "").split())
    for secret in secrets:
        if secret and len(secret) >= 6:
            cleaned = cleaned.replace(secret, "…")
    if len(cleaned) > 180:
        cleaned = cleaned[:177] + "..."
    return cleaned


def _json_request(url, payload, label, secrets=(), headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        if value:
            request.add_header(key, value)
    _send(request, label, secrets)
    return body


def _send_discord(config, notice, message, mail_settings):
    url = config["webhook_url"]
    _json_request(
        url,
        {"content": message, "allowed_mentions": {"parse": []}},
        "Discord",
        secrets=(url,),
    )


def _send_slack(config, notice, message, mail_settings):
    url = config["webhook_url"]
    _json_request(url, {"text": message}, "Slack", secrets=(url,))


def _send_mattermost(config, notice, message, mail_settings):
    url = config["webhook_url"]
    _json_request(url, {"text": message}, "Mattermost", secrets=(url,))


def _send_teams(config, notice, message, mail_settings):
    url = config["webhook_url"]
    colors = {
        EVENT_FINISHED: "2EB886",
        EVENT_FAILED: "D9534F",
        EVENT_INTERRUPTED: "F0AD4E",
        EVENT_STARTED: "5BC0DE",
    }
    _json_request(
        url,
        {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": render_title(notice),
            "themeColor": colors.get(notice.get("event"), "5BC0DE"),
            "title": render_title(notice),
            "text": message,
        },
        "Microsoft Teams",
        secrets=(url,),
    )


def _send_telegram(config, notice, message, mail_settings):
    token = config["bot_token"]
    url = "https://api.telegram.org/bot{}/sendMessage".format(urllib.parse.quote(token, safe=":"))
    _json_request(
        url,
        {"chat_id": config["chat_id"], "text": message},
        "Telegram",
        secrets=(token,),
    )


def _send_webhook(config, notice, message, mail_settings):
    url = config["url"]
    payload = {
        "event": notice.get("event"),
        "job_id": notice.get("job_id"),
        "job_name": notice.get("job_name") or "",
        "protocol": notice.get("protocol") or "",
        "workspace": notice.get("workspace") or "",
        "message": message,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {}
    secret = config.get("secret") or ""
    if secret:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-BioQueue-Signature"] = "sha256=" + digest
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("User-Agent", USER_AGENT)
    for key, value in headers.items():
        request.add_header(key, value)
    _send(request, "webhook", secrets=(url, secret))


def _send_ntfy(config, notice, message, mail_settings):
    url = config["url"]
    token = config.get("token") or ""
    request = urllib.request.Request(url, data=message.encode("utf-8"), method="POST")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Title", render_title(notice))
    priorities = {EVENT_FAILED: "5", EVENT_INTERRUPTED: "4", EVENT_FINISHED: "3", EVENT_STARTED: "2"}
    request.add_header("Priority", priorities.get(notice.get("event"), "3"))
    if token:
        request.add_header("Authorization", "Bearer " + token)
    _send(request, "ntfy", secrets=(token,))


def _send_gotify(config, notice, message, mail_settings):
    base = config["url"].rstrip("/")
    if base.endswith("/message"):
        url = base
    else:
        url = base + "/message"
    token = config["token"]
    priorities = {EVENT_FAILED: 8, EVENT_INTERRUPTED: 5, EVENT_FINISHED: 4, EVENT_STARTED: 2}
    _json_request(
        url,
        {
            "title": render_title(notice),
            "message": message,
            "priority": priorities.get(notice.get("event"), 4),
        },
        "Gotify",
        secrets=(token,),
        headers={"X-Gotify-Key": token},
    )


def _send_pushover(config, notice, message, mail_settings):
    priorities = {EVENT_FAILED: "1", EVENT_INTERRUPTED: "0", EVENT_FINISHED: "0", EVENT_STARTED: "-1"}
    body = urllib.parse.urlencode(
        {
            "token": config["api_token"],
            "user": config["user_key"],
            "title": render_title(notice),
            "message": message,
            "priority": priorities.get(notice.get("event"), "0"),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.pushover.net/1/messages.json",
        data=body,
        method="POST",
    )
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    request.add_header("User-Agent", USER_AGENT)
    _send(request, "Pushover", secrets=(config["api_token"], config["user_key"]))


def _send_email(config, notice, message, mail_settings):
    mail = dict(mail_settings or {})
    if not config.get("smtp_host") and not mail.get("mail_host"):
        mail = load_site_mail()
    own_smtp = bool(config.get("smtp_host"))
    host = config.get("smtp_host") or mail.get("mail_host") or ""
    if not host:
        raise NotificationError("SMTP host is not set. Add it on the hook or in config/custom.conf [mail].")
    port_text = config.get("smtp_port") or ("" if own_smtp else (mail.get("mail_port") or "")) or "587"
    try:
        port = int(port_text)
    except (TypeError, ValueError):
        raise NotificationError("SMTP port is not a number.")
    user = config.get("smtp_user") or ("" if own_smtp else (mail.get("mail_user") or ""))
    password = config.get("smtp_password") or ("" if own_smtp else (mail.get("mail_password") or ""))
    security = config.get("smtp_security") or ""
    if not security and not own_smtp:
        if (mail.get("ssl") or "").lower() == "true":
            security = "ssl"
        elif (mail.get("tls") or "").lower() == "true":
            security = "starttls"
    sender = config.get("sender") or ("" if own_smtp else (mail.get("sender") or "")) or user or config["to"]
    email = EmailMessage()
    email["Subject"] = render_title(notice)
    email["From"] = sender
    email["To"] = config["to"]
    email.set_content(message)
    client = None
    try:
        if security == "ssl" or (security == "" and port == 465):
            client = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT)
        else:
            client = smtplib.SMTP(host, port, timeout=TIMEOUT)
            if security == "starttls" or (security == "" and port == 587):
                client.starttls()
        if user:
            client.login(user, password or "")
        client.send_message(email)
    except NotificationError:
        raise
    except Exception as exc:
        raise NotificationError("Email failed ({}).".format(_redact(str(exc), (password or "", user))))
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass


_SENDERS = {
    "discord": _send_discord,
    "telegram": _send_telegram,
    "slack": _send_slack,
    "teams": _send_teams,
    "mattermost": _send_mattermost,
    "ntfy": _send_ntfy,
    "gotify": _send_gotify,
    "pushover": _send_pushover,
    "email": _send_email,
    "webhook": _send_webhook,
}
