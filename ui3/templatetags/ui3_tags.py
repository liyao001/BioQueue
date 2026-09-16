from django import template
from django.utils.safestring import mark_safe

from QueueDB.models import JobStatus

register = template.Library()

# Worker3 writes .bq_step_N.sh when software is exactly this token. Keep in ui3 only.
SHELL_SOFTWARE = "__SHELL__"

STATUS_ICONS = {
    JobStatus.WRONG: ("fa-circle-xmark", "text-red-600"),
    JobStatus.RESOURCELOCK: ("fa-hourglass-half", "text-orange-500"),
    JobStatus.FINISHED: ("fa-circle-check", "text-green-600"),
    JobStatus.WAITING: ("fa-clock", "text-gray-500"),
    JobStatus.RUNNING: ("fa-circle-play", "text-blue-600"),
    JobStatus.INTERRUPTED: ("fa-circle-pause", "text-yellow-500"),
}


@register.simple_tag(takes_context=True)
def qs_url(context, **updates):
    request = context["request"]
    q = request.GET.copy()
    for key, value in updates.items():
        if value is None or value == "":
            q.pop(key, None)
        else:
            q[key] = value
    encoded = q.urlencode()
    return "?" + encoded if encoded else "?"


@register.simple_tag
def status_badge(job):
    label = dict(JobStatus.choices).get(job.status, str(job.status))
    icon, color = STATUS_ICONS.get(job.status, ("fa-circle", "text-gray-400"))
    return mark_safe(
        '<span class="inline-flex items-center justify-center w-6 h-6 {}" title="{}" aria-label="{}">'
        '<i class="fa-solid {}"></i></span>'.format(color, label, label, icon)
    )


@register.filter
def status_label(value):
    return dict(JobStatus.choices).get(value, str(value))


@register.filter
def is_shell_step(software):
    return str(software or "").strip() == SHELL_SOFTWARE


@register.simple_tag
def shell_software():
    return SHELL_SOFTWARE


@register.simple_tag
def shell_script_placeholder():
    # mark_safe so "{{Job}}" is not re-parsed; quotes/newlines stay valid in HTML attrs.
    return mark_safe(
        'echo &quot;job {{Job}}&quot;&#10;ls &quot;{{Workspace}}&quot;'
    )


@register.filter
def can_edit(obj, user):
    """True if user may mutate this owned-or-public record (ui2 check_owner write)."""
    from ui3 import services

    return services.can_mutate(user, obj)


@register.filter
def format_bytes(value):
    from ui3.files import format_bytes as _format_bytes
    return _format_bytes(value)


@register.inclusion_tag("ui3/partials/running_badge.html", takes_context=True)
def running_badge(context):
    """Server-rendered running-job count for the Dashboard nav badge."""
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    count = 0
    if user is not None and getattr(user, "is_authenticated", False):
        from ui3 import services

        count = services.running_job_count(user)
    label = "99+" if count > 99 else str(count)
    return {"count": count, "label": label}
