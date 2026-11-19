from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .. import services
from ..decorators import ui3_login_required
from ..http import htmx_error, is_htmx, with_toast


def _forbidden(request, message="That access grant was not found."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _context(request):
    return {
        "outgoing": services.outgoing_cross_access(request.user),
        "incoming": services.incoming_cross_access(request.user),
    }


def _refresh(request, message):
    if is_htmx(request):
        response = render(request, "ui3/access/_panel.html", _context(request))
        return with_toast(response, message)
    messages.success(request, message)
    return redirect("ui3:cross_access")


def _error(request, exc):
    if is_htmx(request):
        return htmx_error(str(exc))
    messages.error(request, str(exc))
    return redirect("ui3:cross_access")


def _flag(request, name):
    raw = request.POST.get(name)
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise services.CrossAccessError("Missing {} flag.".format(name))


@ui3_login_required
@require_GET
def cross_access_list(request):
    return render(request, "ui3/access/list.html", _context(request))


@ui3_login_required
@require_POST
def cross_access_create(request):
    try:
        grant, created = services.grant_cross_access(
            request.user,
            request.POST.get("username") or "",
            allow_read=request.POST.get("allow_read") == "1",
            allow_write=request.POST.get("allow_write") == "1",
        )
    except services.CrossAccessError as exc:
        return _error(request, exc)
    verb = "Saved" if created else "Updated"
    message = "{} access for {} ({}).".format(
        verb, grant.grantee.username, services.cross_access_summary(grant)
    )
    return _refresh(request, message)


@ui3_login_required
@require_POST
def cross_access_update(request, pk):
    grant = services.get_owned_cross_access(request.user, pk)
    if grant is None:
        return _forbidden(request)
    try:
        changed = False
        if "allow_read" in request.POST:
            services.set_cross_access_flag(grant, "allow_read", _flag(request, "allow_read"))
            changed = True
        if "allow_write" in request.POST:
            services.set_cross_access_flag(grant, "allow_write", _flag(request, "allow_write"))
            changed = True
        if not changed:
            raise services.CrossAccessError("Choose read or write.")
    except services.CrossAccessError as exc:
        return _error(request, exc)
    message = "Updated access for {} ({}).".format(
        grant.grantee.username, services.cross_access_summary(grant)
    )
    return _refresh(request, message)


@ui3_login_required
@require_POST
def cross_access_delete(request, pk):
    grant = services.get_owned_cross_access(request.user, pk)
    if grant is None:
        return _forbidden(request)
    name = services.revoke_cross_access(grant)
    return _refresh(request, "Revoked {}'s access to your jobs.".format(name))
