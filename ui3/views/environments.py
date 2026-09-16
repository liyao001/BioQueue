from django.contrib import messages
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from QueueDB.models import VirtualEnvironment

from ..decorators import ui3_login_required
from ..http import delegate_for, htmx_error, is_htmx, list_params, querystring, render_htmx, with_toast
from .. import services


VE_TYPES = ("conda", "venv")


def _forbidden(request, message="Virtual environment not found or not accessible."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _env_context(request):
    params = list_params(request)
    q = params.get("q") or ""
    environments = services.search_environments(request.user, q)
    page, paginator = services.paginate(environments, request, params=params)
    return {
        "page_obj": page,
        "paginator": paginator,
        "environments": page.object_list,
        "q": q,
        "filters": params,
        "qs": querystring(request),
        "page_size": page.paginator.per_page,
        "page_size_choices": (12, 24, 36, 48),
        "item_label": "virtual environment",
        "ve_types": VE_TYPES,
    }


def _ve_fields(request):
    name = (request.POST.get("name") or "").strip()
    value = (request.POST.get("value") or "").strip()
    ve_type = (request.POST.get("ve_type") or "conda").strip()
    if ve_type not in VE_TYPES:
        ve_type = "conda"
    activation = (request.POST.get("activation_command") or "").strip()
    return name, value, ve_type, activation


@ui3_login_required
@require_http_methods(["GET"])
def environment_list(request):
    ctx = _env_context(request)
    return render_htmx(request, "ui3/environments/list.html", "ui3/environments/_table.html", ctx)


@ui3_login_required
@require_POST
def environment_create(request):
    name, value, ve_type, activation = _ve_fields(request)
    if not name or not value:
        if is_htmx(request):
            return htmx_error("Name and value are required.")
        messages.error(request, "Name and value are required.")
        return redirect("ui3:environments")
    if len(name) > 50:
        if is_htmx(request):
            return htmx_error("Name is too long (max 50 characters).")
        messages.error(request, "Name is too long (max 50 characters).")
        return redirect("ui3:environments")
    try:
        VirtualEnvironment.objects.create(
            name=name,
            ve_type=ve_type,
            value=value,
            activation_command=activation or None,
            user=delegate_for(request.user),
        )
    except IntegrityError:
        if is_htmx(request):
            return htmx_error("A virtual environment with this name already exists.")
        messages.error(request, "A virtual environment with this name already exists.")
        return redirect("ui3:environments")
    if is_htmx(request):
        ctx = _env_context(request)
        response = render(request, "ui3/environments/_table.html", ctx)
        return with_toast(response, "Virtual environment created.")
    messages.success(request, "Virtual environment created.")
    return redirect("ui3:environments")


@ui3_login_required
@require_http_methods(["GET", "POST"])
def environment_edit(request, pk):
    env = services.get_owned_environment(request.user, pk)
    if env is None:
        return _forbidden(request)
    if request.method == "GET":
        return render(request, "ui3/environments/_edit_modal.html", {"env": env, "ve_types": VE_TYPES})
    name, value, ve_type, activation = _ve_fields(request)
    if not name or not value:
        if is_htmx(request):
            return htmx_error("Name and value are required.")
        return HttpResponseBadRequest("Name and value are required.")
    if len(name) > 50:
        if is_htmx(request):
            return htmx_error("Name is too long (max 50 characters).")
        return HttpResponseBadRequest("Name is too long (max 50 characters).")
    env.name = name
    env.ve_type = ve_type
    env.value = value
    env.activation_command = activation or None
    try:
        env.save()
    except IntegrityError:
        if is_htmx(request):
            return htmx_error("A virtual environment with this name already exists.")
        return HttpResponseBadRequest("A virtual environment with this name already exists.")
    if is_htmx(request):
        ctx = _env_context(request)
        response = render(request, "ui3/environments/_table.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Virtual environment updated.")
    messages.success(request, "Virtual environment updated.")
    return redirect("ui3:environments")


@ui3_login_required
@require_POST
def environment_delete(request, pk):
    env = services.get_owned_environment(request.user, pk)
    if env is None:
        return _forbidden(request)
    name = env.name
    try:
        env.delete()
    except ProtectedError:
        if is_htmx(request):
            return htmx_error("Cannot delete virtual environment '{}' because steps still use it.".format(name))
        messages.error(request, "Cannot delete virtual environment '{}' because steps still use it.".format(name))
        return redirect("ui3:environments")
    if is_htmx(request):
        ctx = _env_context(request)
        response = render(request, "ui3/environments/_table.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Virtual environment '{}' deleted.".format(name))
    messages.success(request, "Virtual environment '{}' deleted.".format(name))
    return redirect("ui3:environments")
