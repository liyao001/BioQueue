from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from QueueDB.notifications import (
    DEFAULT_EVENTS,
    EVENT_KEYS,
    EVENT_LABELS,
    NotificationError,
    PROVIDERS,
    deliver,
    form_fields,
    provider_choices,
    provider_help,
    sample_notice,
    stored_config_text,
)

from ..decorators import ui3_login_required
from ..http import htmx_error, is_htmx, toast_html, with_toast
from .. import services


def _forbidden(request, message="Notification hook not found."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _context(request):
    return {
        "hooks": services.notification_hooks_for(request.user),
        "providers": provider_choices(),
        "event_choices": [(key, EVENT_LABELS[key]) for key in EVENT_KEYS],
        "selected_events": list(DEFAULT_EVENTS),
        "enabled": True,
        "provider_key": "discord",
        "provider_help": provider_help("discord"),
        "fields": form_fields("discord"),
    }


def _fields_context(provider, hook=None):
    if provider not in PROVIDERS:
        provider = "discord"
    values = {}
    keep_secrets = False
    if hook is not None and hook.provider == provider:
        values = stored_config_text(hook.config)
        keep_secrets = True
    return {
        "provider_key": provider,
        "provider_help": provider_help(provider),
        "fields": form_fields(provider, values, keep_secrets=keep_secrets),
    }


@ui3_login_required
@require_GET
def notification_list(request):
    return render(request, "ui3/notifications/list.html", _context(request))


@ui3_login_required
@require_GET
def notification_fields(request):
    provider = (request.GET.get("provider") or "discord").strip()
    hook = None
    hook_id = request.GET.get("hook") or ""
    if hook_id.isdigit():
        hook = services.get_owned_notification_hook(request.user, int(hook_id))
    return render(request, "ui3/notifications/_fields.html", _fields_context(provider, hook))


@ui3_login_required
@require_POST
def notification_create(request):
    try:
        services.create_notification_hook(request.user, request.POST)
    except NotificationError as exc:
        if is_htmx(request):
            return htmx_error(str(exc))
        messages.error(request, str(exc))
        return redirect("ui3:notifications")
    if is_htmx(request):
        response = render(request, "ui3/notifications/_table.html", _context(request))
        return with_toast(response, "Notification hook saved.")
    messages.success(request, "Notification hook saved.")
    return redirect("ui3:notifications")


@ui3_login_required
@require_http_methods(["GET", "POST"])
def notification_edit(request, pk):
    hook = services.get_owned_notification_hook(request.user, pk)
    if hook is None:
        return _forbidden(request)
    if request.method == "GET":
        ctx = _fields_context(hook.provider, hook)
        ctx.update(
            {
                "hook": hook,
                "providers": provider_choices(),
                "event_choices": [(key, EVENT_LABELS[key]) for key in EVENT_KEYS],
                "selected_events": hook.event_keys(),
                "enabled": bool(hook.enabled),
            }
        )
        return render(request, "ui3/notifications/_edit_modal.html", ctx)
    try:
        services.update_notification_hook(hook, request.POST)
    except NotificationError as exc:
        if is_htmx(request):
            return htmx_error(str(exc))
        messages.error(request, str(exc))
        return redirect("ui3:notifications")
    if is_htmx(request):
        response = render(request, "ui3/notifications/_table.html", _context(request))
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Notification hook updated.")
    messages.success(request, "Notification hook updated.")
    return redirect("ui3:notifications")


@ui3_login_required
@require_POST
def notification_delete(request, pk):
    hook = services.get_owned_notification_hook(request.user, pk)
    if hook is None:
        return _forbidden(request)
    name = hook.name
    hook.delete()
    if is_htmx(request):
        response = render(request, "ui3/notifications/_table.html", _context(request))
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Notification hook '{}' deleted.".format(name))
    messages.success(request, "Notification hook '{}' deleted.".format(name))
    return redirect("ui3:notifications")


@ui3_login_required
@require_POST
def notification_test(request, pk):
    hook = services.get_owned_notification_hook(request.user, pk)
    if hook is None:
        return _forbidden(request)
    try:
        deliver(hook, sample_notice(hook))
    except NotificationError as exc:
        if is_htmx(request):
            return htmx_error(str(exc))
        messages.error(request, str(exc))
        return redirect("ui3:notifications")
    if is_htmx(request):
        return HttpResponse(toast_html("Test message sent."))
    messages.success(request, "Test message sent.")
    return redirect("ui3:notifications")
