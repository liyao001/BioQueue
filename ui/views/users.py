from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from ..decorators import ui3_login_required
from ..http import htmx_error, is_htmx, list_params, querystring, render_htmx, with_toast
from .. import services


def _forbidden(request, message="Staff access required."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _users_url(request):
    qs = querystring(request)
    url = reverse("ui3:users")
    return "{}?{}".format(url, qs) if qs else url


def _post_flag(request, name):
    raw = request.POST.get(name)
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise services.UserManageError("Missing {} flag.".format(name))


def _users_context(request):
    params = list_params(request)
    q = params.get("q") or ""
    state = (params.get("state") or "all").strip().lower()
    if state not in services.USER_STATES:
        state = "all"
    users = services.search_users(request.user, q, state)
    page, paginator = services.paginate(users, request, params=params)
    return {
        "page_obj": page,
        "paginator": paginator,
        "users": page.object_list,
        "q": q,
        "state": state,
        "pending_count": services.pending_user_count(request.user),
        "filters": params,
        "qs": querystring(request),
        "page_size": page.paginator.per_page,
        "page_size_choices": (12, 24, 36, 48),
        "item_label": "account",
    }


def _refresh(request, message):
    ctx = _users_context(request)
    if is_htmx(request):
        response = render(request, "ui3/users/_table.html", ctx)
        return with_toast(response, message)
    messages.success(request, message)
    return redirect(_users_url(request))


def _manage_error(request, exc):
    if is_htmx(request):
        return htmx_error(str(exc))
    messages.error(request, str(exc))
    return redirect(_users_url(request))


@ui3_login_required
@require_http_methods(["GET"])
def user_list(request):
    if not getattr(request.user, "is_staff", False):
        return _forbidden(request)
    ctx = _users_context(request)
    return render_htmx(request, "ui3/users/list.html", "ui3/users/_table.html", ctx)


@ui3_login_required
@require_POST
def user_create(request):
    if not getattr(request.user, "is_staff", False):
        return _forbidden(request)
    try:
        user = services.create_managed_user(
            request.user,
            username=request.POST.get("username") or "",
            password=request.POST.get("password") or "",
            password_2=request.POST.get("password_2") or "",
            email=request.POST.get("email") or "",
            first_name=request.POST.get("first_name") or "",
            last_name=request.POST.get("last_name") or "",
            activate=request.POST.get("activate") == "1",
            staff=request.POST.get("staff") == "1",
        )
    except services.UserManageError as exc:
        return _manage_error(request, exc)
    return _refresh(request, "Created account {}.".format(user.username))


@ui3_login_required
@require_POST
def user_activate(request, pk):
    if not getattr(request.user, "is_staff", False):
        return _forbidden(request)
    target = services.get_managed_user(pk)
    try:
        active = _post_flag(request, "active")
        was_pending = services.user_is_pending(target)
        user = services.set_user_active(request.user, target, active)
    except services.UserManageError as exc:
        return _manage_error(request, exc)
    if active:
        msg = "Approved {}.".format(user.username) if was_pending else "Reactivated {}.".format(user.username)
    else:
        msg = "Deactivated {}.".format(user.username)
    return _refresh(request, msg)


@ui3_login_required
@require_POST
def user_staff(request, pk):
    if not getattr(request.user, "is_staff", False):
        return _forbidden(request)
    target = services.get_managed_user(pk)
    try:
        staff = _post_flag(request, "staff")
        user = services.set_user_staff(request.user, target, staff)
    except services.UserManageError as exc:
        return _manage_error(request, exc)
    if staff:
        msg = "{} is now staff.".format(user.username)
    else:
        msg = "Removed staff from {}.".format(user.username)
    return _refresh(request, msg)
