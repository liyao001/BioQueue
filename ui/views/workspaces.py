from django.contrib import messages
from django.db.models import ProtectedError
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from QueueDB.models import Workspace

from ..decorators import ui3_login_required
from ..http import delegate_for, htmx_error, is_htmx, list_params, querystring, render_htmx, with_toast
from .. import services


def _forbidden(request, message="Workspace not found or not accessible."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _ws_context(request):
    params = list_params(request)
    q = params.get("q") or ""
    workspaces = services.search_workspaces(request.user, q)
    page, paginator = services.paginate(workspaces, request, params=params)
    return {
        "page_obj": page,
        "paginator": paginator,
        "workspaces": page.object_list,
        "q": q,
        "filters": params,
        "qs": querystring(request),
        "page_size": page.paginator.per_page,
        "page_size_choices": (12, 24, 36, 48),
        "item_label": "workspace",
    }


@ui3_login_required
@require_http_methods(["GET"])
def workspace_list(request):
    ctx = _ws_context(request)
    return render_htmx(request, "ui3/workspaces/list.html", "ui3/workspaces/_table.html", ctx)


@ui3_login_required
@require_POST
def workspace_create(request):
    name = (request.POST.get("name") or "").strip()
    if not name:
        if is_htmx(request):
            return htmx_error("Name is required.")
        messages.error(request, "Name is required.")
        return redirect("ui3:workspaces")
    if len(name) > 255:
        if is_htmx(request):
            return htmx_error("Name is too long (max 255 characters).")
        messages.error(request, "Name is too long (max 255 characters).")
        return redirect("ui3:workspaces")
    Workspace.objects.create(
        name=name,
        description=request.POST.get("description") or "",
        user=delegate_for(request.user),
    )
    if is_htmx(request):
        ctx = _ws_context(request)
        response = render(request, "ui3/workspaces/_table.html", ctx)
        return with_toast(response, "Workspace created.")
    messages.success(request, "Workspace created.")
    return redirect("ui3:workspaces")


@ui3_login_required
@require_http_methods(["GET", "POST"])
def workspace_edit(request, pk):
    ws = services.get_owned_workspace(request.user, pk)
    if ws is None:
        return _forbidden(request)
    if request.method == "GET":
        return render(request, "ui3/workspaces/_edit_modal.html", {"ws": ws})
    name = (request.POST.get("name") or "").strip()
    if not name:
        if is_htmx(request):
            return htmx_error("Name is required.")
        return HttpResponseBadRequest("Name is required.")
    if len(name) > 255:
        if is_htmx(request):
            return htmx_error("Name is too long (max 255 characters).")
        return HttpResponseBadRequest("Name is too long (max 255 characters).")
    ws.name = name
    ws.description = request.POST.get("description") or ""
    ws.save()
    if is_htmx(request):
        ctx = _ws_context(request)
        response = render(request, "ui3/workspaces/_table.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Workspace updated.")
    messages.success(request, "Workspace updated.")
    return redirect("ui3:workspaces")


@ui3_login_required
@require_POST
def workspace_delete(request, pk):
    ws = services.get_owned_workspace(request.user, pk)
    if ws is None:
        return _forbidden(request)
    name = ws.name
    try:
        ws.delete()
    except ProtectedError:
        if is_htmx(request):
            return htmx_error("Cannot delete workspace '{}' because jobs still use it.".format(name))
        messages.error(request, "Cannot delete workspace '{}' because jobs still use it.".format(name))
        return redirect("ui3:workspaces")
    if is_htmx(request):
        ctx = _ws_context(request)
        response = render(request, "ui3/workspaces/_table.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Workspace '{}' deleted.".format(name))
    messages.success(request, "Workspace '{}' deleted.".format(name))
    return redirect("ui3:workspaces")
