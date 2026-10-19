from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from QueueDB.models import Reference

from ..decorators import ui3_login_required
from ..http import delegate_for, htmx_error, is_htmx, list_params, querystring, render_htmx, with_toast
from .. import services


def _forbidden(request, message="Reference not found or not accessible."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _ref_context(request):
    params = list_params(request)
    q = params.get("q") or ""
    refs = services.search_references(request.user, q)
    page, paginator = services.paginate(refs, request, params=params)
    return {
        "page_obj": page,
        "paginator": paginator,
        "references": page.object_list,
        "q": q,
        "filters": params,
        "qs": querystring(request),
        "page_size": page.paginator.per_page,
        "page_size_choices": (12, 24, 36, 48),
        "item_label": "reference",
    }


@ui3_login_required
@require_http_methods(["GET"])
def reference_list(request):
    ctx = _ref_context(request)
    return render_htmx(request, "ui3/references/list.html", "ui3/references/_table.html", ctx)


@ui3_login_required
@require_POST
def reference_create(request):
    name = (request.POST.get("name") or "").strip()
    path = (request.POST.get("path") or "").strip()
    if not name or not path:
        if is_htmx(request):
            return htmx_error("Name and path are required.")
        messages.error(request, "Name and path are required.")
        return redirect("ui3:references")
    if len(name) > 255:
        if is_htmx(request):
            return htmx_error("Name is too long (max 255 characters).")
        messages.error(request, "Name is too long (max 255 characters).")
        return redirect("ui3:references")
    if len(path) > 500:
        if is_htmx(request):
            return htmx_error("Path is too long (max 500 characters).")
        messages.error(request, "Path is too long (max 500 characters).")
        return redirect("ui3:references")
    Reference.objects.create(
        name=name,
        path=path,
        description=request.POST.get("description") or "",
        user=delegate_for(request.user),
    )
    if is_htmx(request):
        ctx = _ref_context(request)
        response = render(request, "ui3/references/_table.html", ctx)
        return with_toast(response, "Reference created.")
    messages.success(request, "Reference created.")
    return redirect("ui3:references")


@ui3_login_required
@require_http_methods(["GET", "POST"])
def reference_edit(request, pk):
    ref = services.get_owned_reference(request.user, pk)
    if ref is None:
        return _forbidden(request)
    if request.method == "GET":
        return render(request, "ui3/references/_edit_modal.html", {"ref": ref})
    name = (request.POST.get("name") or "").strip()
    path = (request.POST.get("path") or "").strip()
    if not name or not path:
        if is_htmx(request):
            return htmx_error("Name and path are required.")
        return HttpResponseBadRequest("Name and path are required.")
    if len(name) > 255:
        if is_htmx(request):
            return htmx_error("Name is too long (max 255 characters).")
        return HttpResponseBadRequest("Name is too long (max 255 characters).")
    if len(path) > 500:
        if is_htmx(request):
            return htmx_error("Path is too long (max 500 characters).")
        return HttpResponseBadRequest("Path is too long (max 500 characters).")
    ref.name = name
    ref.path = path
    ref.description = request.POST.get("description") or ""
    ref.save()
    if is_htmx(request):
        ctx = _ref_context(request)
        response = render(request, "ui3/references/_table.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Reference updated.")
    messages.success(request, "Reference updated.")
    return redirect("ui3:references")


@ui3_login_required
@require_POST
def reference_delete(request, pk):
    ref = services.get_owned_reference(request.user, pk)
    if ref is None:
        return _forbidden(request)
    name = ref.name
    ref.delete()
    if is_htmx(request):
        ctx = _ref_context(request)
        response = render(request, "ui3/references/_table.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Reference '{}' deleted.".format(name))
    messages.success(request, "Reference '{}' deleted.".format(name))
    return redirect("ui3:references")
