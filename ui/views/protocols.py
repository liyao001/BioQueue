from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

import json

from QueueDB.models import ProtocolList, Step, _recompute_protocol_ver

from ..decorators import ui3_login_required
from ..http import combo_query, delegate_for, htmx_error, int_or_none, is_htmx, list_params, querystring, render_htmx, with_toast
from .. import services


def _forbidden(request, message="Protocol not found or not accessible."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _editor_chrome(selected=None):
    if selected is None:
        return {
            "editor_url": reverse("ui3:protocol_template_create_edit"),
            "editor_form": "#protocol-template-create-form",
            "editor_submit_label": "Create protocol",
            "editor_hint": (
                "Draft changes stay on this page until you create the protocol. "
                "Environments use their names so exported templates can use matching "
                "environments on another installation."
            ),
        }
    return {
        "editor_url": reverse("ui3:protocol_template_edit", args=[selected.id]),
        "editor_form": "#protocol-meta-form",
        "editor_submit_label": "Save protocol",
        "editor_hint": (
            "Changes are saved only when you select Save protocol. "
            "Environments use their names so exported templates can use matching "
            "environments on another installation."
        ),
    }


def _protocol_page_context(request, selected=None):
    params = list_params(request)
    q = params.get("q") or ""
    ordering = params.get("ordering") or "-id"
    protocols = services.search_protocols(request.user, q, ordering=ordering)
    page, paginator = services.paginate(protocols, request, params=params)
    select_id = int_or_none(params.get("select"))
    if selected is None and select_id:
        selected = services.get_visible_protocol(request.user, select_id)
    steps = services.protocol_steps(selected) if selected else []
    environments = services.visible_environments(request.user)
    shortcuts = list(services.visible_shortcuts(request.user, protocol=selected)) if selected else []
    ctx = {
        "page_obj": page,
        "paginator": paginator,
        "protocols": page.object_list,
        "selected": selected,
        "can_edit_selected": services.can_mutate(request.user, selected) if selected else False,
        "steps": steps,
        "shortcuts": shortcuts,
        "shortcut_presets": services.shortcut_presets() if selected else [],
        "token_list": services.autocomplete_tokens(request.user),
        "environments": environments,
        "filters": params,
        "qs": querystring(request),
        "q": q,
        "ordering": ordering,
        "page_size": page.paginator.per_page,
        "page_size_choices": (12, 24, 36, 48),
        "item_label": "protocol",
    }
    ctx.update(services.template_context(selected))
    if ctx["template_active"]:
        try:
            ctx.update(services.template_editor_context(
                json.loads(selected.template), environments, preview_samples=_preview_count(request),
            ))
            ctx.update(_editor_chrome(selected))
        except (ValueError, TypeError, KeyError):
            pass  # Keep the raw JSON editor available to repair invalid data.
    return ctx


def _preview_count(request):
    raw = request.POST.get("preview_samples") or request.GET.get("preview_samples") or 2
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 2


def _template_create_context(request, document, form=None, error=None, mode="visual"):
    environments = services.visible_environments(request.user)
    ctx = {
        "environments": environments,
        "error": error,
        "form": form or {},
        "token_list": services.autocomplete_tokens(request.user),
        "selected": None,
    }
    ctx.update(services.template_editor_context(
        document, environments, mode, preview_samples=_preview_count(request),
    ))
    ctx.update(_editor_chrome())
    ctx["editor_open"] = True
    return ctx


def _posted_rename(request):
    try:
        path = json.loads(request.POST.get("editor_path") or "[]")
    except json.JSONDecodeError:
        return ""
    if not isinstance(path, list) or len(path) < 2 or not isinstance(path[1], str):
        return ""
    return request.POST.get("br:{}".format(path[1]), "")


def _create_error_page(request, raw, error, document=None):
    """Redisplay the create form without dropping a draft that cannot be drawn."""
    try:
        if document is None:
            document = json.loads(raw) if (raw or "").strip() else services.blank_template_document()
        ctx = _template_create_context(request, document, form=request.POST, error=error)
    except (json.JSONDecodeError, services.ProtocolTemplateError, ValueError, TypeError, KeyError, IndexError):
        ctx = _template_create_context(
            request, services.blank_template_document(), form=request.POST, error=error, mode="json",
        )
        ctx["editor"]["source"] = raw or ""
    return render(request, "ui3/protocols/new_template.html", ctx, status=400)


@ui3_login_required
@require_http_methods(["GET"])
def protocol_list(request):
    ctx = _protocol_page_context(request)
    return render_htmx(request, "ui3/protocols/list.html", "ui3/protocols/_workspace.html", ctx)


@ui3_login_required
@require_http_methods(["GET"])
def protocol_detail(request, pk):
    proto = services.get_visible_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request) and request.headers.get("HX-Target") == "protocol-detail":
        return render(request, "ui3/protocols/_detail.html", ctx)
    return render_htmx(request, "ui3/protocols/list.html", "ui3/protocols/_workspace.html", ctx)


@ui3_login_required
@require_http_methods(["GET", "POST"])
def protocol_create(request):
    environments = services.visible_environments(request.user)
    if request.method == "GET":
        return render(
            request,
            "ui3/protocols/new.html",
            {
                "environments": environments,
                "error": None,
                "form": {},
                "token_list": services.autocomplete_tokens(request.user),
            },
        )
    name = (request.POST.get("name") or "").strip()
    if not name:
        return render(
            request,
            "ui3/protocols/new.html",
            {
                "environments": environments,
                "error": "Name is required.",
                "form": request.POST,
                "token_list": services.autocomplete_tokens(request.user),
            },
            status=400,
        )
    user = delegate_for(request.user)
    proto = ProtocolList.objects.create(
        name=name,
        description=(request.POST.get("description") or "").strip() or None,
        user=user,
    )
    softwares = request.POST.getlist("software")
    parameters = request.POST.getlist("parameter")
    envs = request.POST.getlist("env")
    order = 1
    for i, software in enumerate(softwares):
        software = (software or "").strip()
        if not software:
            continue
        parameter = parameters[i] if i < len(parameters) else ""
        env = None
        if i < len(envs) and envs[i]:
            env = environments.filter(pk=int_or_none(envs[i])).first()
        services.create_step(proto, software, parameter, order, env=env, user=user)
        order += 1
    messages.success(request, "Protocol '{}' created.".format(proto.name))
    return redirect(reverse("ui3:protocols") + "?select={}".format(proto.id))


@ui3_login_required
@require_http_methods(["GET", "POST"])
def protocol_template_create(request):
    if request.method == "GET":
        return render(
            request,
            "ui3/protocols/new_template.html",
            _template_create_context(request, services.blank_template_document()),
        )
    raw = request.POST.get("template") or ""
    name = (request.POST.get("name") or "").strip()
    document = None
    try:
        document = services.read_template_form(request.POST)
        template = services.normalize_template(document)
        user = delegate_for(request.user)
        services.resolve_template_environments(json.loads(template), user.id)
    except json.JSONDecodeError:
        return _create_error_page(request, raw, "Template is not valid JSON.")
    except services.ProtocolTemplateError as exc:
        return _create_error_page(request, raw, str(exc), document)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return _create_error_page(request, raw, "Invalid template field: {}".format(exc), document)
    if not name:
        return _create_error_page(request, template, "Name is required.", json.loads(template))
    proto = ProtocolList.objects.create(
        name=name,
        description=(request.POST.get("description") or "").strip() or None,
        user=user,
        template=template,
    )
    _recompute_protocol_ver(proto)
    messages.success(request, "Template protocol '{}' created.".format(proto.name))
    return redirect(reverse("ui3:protocols") + "?select={}".format(proto.id))


@ui3_login_required
@require_POST
def protocol_template_create_edit(request):
    try:
        document = services.read_template_form(request.POST)
        action = request.POST.get("editor_action", "")
        document = services.edit_template_document(
            document, action, request.POST.get("editor_path", ""), request.POST.get("editor_block_name", ""),
            _posted_rename(request),
        )
        mode = "json" if action in ("show_json", "format") else "visual"
        context = _template_create_context(request, document, form=request.POST, mode=mode)
    except (ValueError, TypeError, KeyError, IndexError, services.ProtocolTemplateError) as exc:
        return htmx_error("Cannot update template draft: {}".format(exc))
    return render(request, "ui3/protocols/_template_editor.html", context)


@ui3_login_required
@require_POST
def protocol_update(request, pk):
    proto = services.get_owned_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    name = (request.POST.get("name") or "").strip()
    if not name:
        if is_htmx(request):
            return htmx_error("Name is required.")
        return HttpResponseBadRequest("Name is required.")
    proto.name = name
    if "description" in request.POST:
        proto.description = request.POST.get("description") or None
    if "template" in request.POST:
        try:
            incoming = request.POST.get("template") or ""
            proto.template = services.normalize_template(services.read_template_form(request.POST)) if incoming.strip() else ""
            if proto.template:
                services.resolve_template_environments(json.loads(proto.template), proto.user_id)
        except json.JSONDecodeError:
            if is_htmx(request):
                return htmx_error("Template is not valid JSON.")
            return HttpResponseBadRequest("Template is not valid JSON.")
        except services.ProtocolTemplateError as exc:
            if is_htmx(request):
                return htmx_error(str(exc))
            return HttpResponseBadRequest(str(exc))
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            return htmx_error("Invalid template field: {}".format(exc)) if is_htmx(request) else HttpResponseBadRequest("Invalid template field.")
    proto.save()
    if "template" in request.POST:
        _recompute_protocol_ver(proto)
        proto.refresh_from_db()
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request):
        response = render(request, "ui3/protocols/_workspace.html", ctx)
        return with_toast(response, "Protocol updated.")
    messages.success(request, "Protocol updated.")
    return redirect("ui3:protocols")


@ui3_login_required
@require_POST
def protocol_template_edit(request, pk):
    proto = services.get_owned_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    try:
        document = services.read_template_form(request.POST)
        action = request.POST.get("editor_action", "")
        document = services.edit_template_document(
            document, action, request.POST.get("editor_path", ""), request.POST.get("editor_block_name", ""),
            _posted_rename(request),
        )
        mode = "json" if action in ("show_json", "format") else "visual"
        context = services.template_editor_context(
            document, services.visible_environments(request.user), mode, preview_samples=_preview_count(request),
        )
        context.update(_editor_chrome(proto))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return htmx_error("Cannot update template draft: {}".format(exc))
    context["selected"] = proto
    return render(request, "ui3/protocols/_template_editor.html", context)


@ui3_login_required
@require_POST
def protocol_delete(request, pk):
    proto = services.get_owned_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    name = proto.name
    proto.delete()
    if is_htmx(request):
        ctx = _protocol_page_context(request)
        response = render(request, "ui3/protocols/_workspace.html", ctx)
        return with_toast(response, "Protocol '{}' deleted.".format(name))
    messages.success(request, "Protocol '{}' deleted.".format(name))
    return redirect("ui3:protocols")


@ui3_login_required
@require_POST
def protocol_clone(request, pk):
    proto = services.get_visible_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    name = (request.POST.get("name") or "").strip() or "{} (copy)".format(proto.name)
    copy_description = bool(request.POST.get("copy_description"))
    copy_shortcuts = bool(request.POST.get("copy_shortcuts"))
    dest = services.clone_protocol(
        proto,
        name,
        delegate_for(request.user),
        copy_description=copy_description,
        copy_shortcuts=copy_shortcuts,
    )
    if is_htmx(request):
        ctx = _protocol_page_context(request, selected=dest)
        response = render(request, "ui3/protocols/_workspace.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Protocol cloned.")
    messages.success(request, "Protocol cloned.")
    return redirect(reverse("ui3:protocols") + "?select={}".format(dest.id))


def _share_error(request, message, pk=None):
    if is_htmx(request):
        return htmx_error(message)
    messages.error(request, message)
    if pk:
        return redirect(reverse("ui3:protocols") + "?select={}".format(pk))
    return redirect("ui3:protocols")


@ui3_login_required
@require_POST
def protocol_share(request, pk):
    proto = services.get_owned_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    try:
        recipient = services.find_share_recipient(request.POST.get("peer") or "")
    except services.ShareProtocolError as exc:
        return _share_error(request, str(exc), pk)
    if recipient.id == proto.user_id:
        return _share_error(request, "You can not share a protocol with yourself.", pk)
    _dest, added_envs, added_refs = services.share_protocol(proto, recipient)
    msg = "Shared '{}' with {}.".format(proto.name, recipient.username)
    added = []
    if added_envs:
        added.append("environments {}".format(", ".join(added_envs)))
    if added_refs:
        added.append("references {}".format(", ".join(added_refs)))
    if added:
        msg += " Added {}.".format(" and ".join(added))
    if is_htmx(request):
        ctx = _protocol_page_context(request, selected=proto)
        response = render(request, "ui3/protocols/_workspace.html", ctx)
        return with_toast(response, msg)
    messages.success(request, msg)
    return redirect(reverse("ui3:protocols") + "?select={}".format(proto.id))


def _import_error(request, message):
    if is_htmx(request):
        return htmx_error(message)
    messages.error(request, message)
    return redirect("ui3:protocols")


@ui3_login_required
@require_http_methods(["GET"])
def protocol_export(request, pk):
    proto = services.get_visible_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    body = services.protocol_json_text(proto, request.user)
    filename = services.protocol_json_filename(proto.name)
    response = HttpResponse(body, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="{}"'.format(filename.replace('"', ""))
    return response


@ui3_login_required
@require_POST
def protocol_import(request):
    try:
        proto, missing, env_notes = services.import_protocol_from_upload(request.user, request.FILES.get("file"))
    except services.ProtocolImportError as exc:
        return _import_error(request, str(exc))
    msg = "Protocol '{}' imported.".format(proto.name)
    if missing:
        msg += " Missing references: {}.".format(", ".join(missing))
    if env_notes:
        msg += " Environment recipes left unchanged: {}.".format(", ".join(env_notes))
    if is_htmx(request):
        ctx = _protocol_page_context(request, selected=proto)
        response = render(request, "ui3/protocols/_workspace.html", ctx)
        return with_toast(response, msg)
    messages.success(request, msg)
    return redirect(reverse("ui3:protocols") + "?select={}".format(proto.id))


@ui3_login_required
@require_http_methods(["GET"])
def protocol_step_row(request):
    environments = services.visible_environments(request.user)
    return render(request, "ui3/protocols/_step_draft_row.html", {"environments": environments})


@ui3_login_required
@require_http_methods(["GET"])
def environment_options(request):
    items = list(
        services.filter_environment_choices(
            services.visible_environments(request.user),
            combo_query(request),
        )
    )
    empty_label = (request.GET.get("empty") or "").strip() or "No environment"
    pin_id = int_or_none(request.GET.get("pin"))
    if pin_id and not any(getattr(i, "id", None) == pin_id for i in items):
        pinned = services.visible_environments(request.user).filter(pk=pin_id).first()
        if pinned is not None:
            items = [pinned] + items
    return render(
        request,
        "ui3/jobs/_combo_options.html",
        {"items": items, "empty_label": empty_label, "kind": "environment"},
    )


@ui3_login_required
@require_POST
def step_create(request, pk):
    proto = services.get_owned_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    software = (request.POST.get("software") or "").strip()
    if not software:
        if is_htmx(request):
            return htmx_error("Software is required.")
        return HttpResponseBadRequest("Software is required.")
    steps = list(services.protocol_steps(proto))
    next_order = (max(s.step_order for s in steps) + 1) if steps else 1
    env = None
    env_id = int_or_none(request.POST.get("env"))
    if env_id:
        env = services.visible_environments(request.user).filter(pk=env_id).first()
    services.create_step(
        proto,
        software,
        request.POST.get("parameter") or "",
        next_order,
        env=env,
        user=delegate_for(request.user),
    )
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request):
        response = render(request, "ui3/protocols/_detail.html", ctx)
        return with_toast(response, "Step added.")
    return redirect("ui3:protocol_detail", pk=proto.id)


@ui3_login_required
@require_http_methods(["GET", "POST"])
def step_edit(request, pk):
    step = Step.objects.select_related("parent", "env").filter(pk=pk).first()
    if step is None:
        return HttpResponseForbidden("Step not found.")
    proto = services.get_owned_protocol(request.user, step.parent_id)
    if proto is None:
        return _forbidden(request)
    environments = services.visible_environments(request.user)
    if request.method == "GET":
        return render(
            request,
            "ui3/protocols/_step_modal.html",
            {
                "step": step,
                "protocol": proto,
                "environments": environments,
                "token_list": services.autocomplete_tokens(request.user),
            },
        )
    software = (request.POST.get("software") or "").strip()
    if not software:
        if is_htmx(request):
            return htmx_error("Software is required.")
        return HttpResponseBadRequest("Software is required.")
    step.software = software
    step.parameter = request.POST.get("parameter") or ""
    step.hash = services.compute_step_hash(step.software, step.parameter)
    env_id = int_or_none(request.POST.get("env"))
    step.env = environments.filter(pk=env_id).first() if env_id else None
    step.save()
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request):
        response = render(request, "ui3/protocols/_detail.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Step updated.")
    messages.success(request, "Step updated.")
    return redirect("ui3:protocol_detail", pk=proto.id)


@ui3_login_required
@require_POST
def step_delete(request, pk):
    step = Step.objects.select_related("parent").filter(pk=pk).first()
    if step is None:
        return HttpResponseForbidden("Step not found.")
    proto = services.get_owned_protocol(request.user, step.parent_id)
    if proto is None:
        return _forbidden(request)
    step.delete()
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request):
        response = render(request, "ui3/protocols/_detail.html", ctx)
        return with_toast(response, "Step deleted.")
    return redirect("ui3:protocol_detail", pk=proto.id)


@ui3_login_required
@require_POST
def step_move(request, pk):
    step = Step.objects.select_related("parent").filter(pk=pk).first()
    if step is None:
        return HttpResponseForbidden("Step not found.")
    proto = services.get_owned_protocol(request.user, step.parent_id)
    if proto is None:
        return _forbidden(request)
    direction = request.POST.get("direction") or "up"
    services.swap_step_order(step, direction)
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request):
        return render(request, "ui3/protocols/_detail.html", ctx)
    return redirect("ui3:protocol_detail", pk=proto.id)


@ui3_login_required
@require_POST
def step_reorder(request, pk):
    proto = services.get_owned_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    raw = (request.POST.get("order") or "").replace(" ", ",")
    ordered_ids = [part for part in raw.split(",") if part.strip()]
    if not ordered_ids:
        if is_htmx(request):
            return htmx_error("Step order is required.")
        return HttpResponseBadRequest("Step order is required.")
    services.reorder_protocol_steps(proto, ordered_ids)
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request):
        return render(request, "ui3/protocols/_detail.html", ctx)
    return redirect("ui3:protocol_detail", pk=proto.id)


def _shortcut_refresh(request, proto, message):
    ctx = _protocol_page_context(request, selected=proto)
    if is_htmx(request):
        response = render(request, "ui3/protocols/_detail.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, message)
    messages.success(request, message)
    return redirect(reverse("ui3:protocols") + "?select={}".format(proto.id))


@ui3_login_required
@require_POST
def shortcut_create(request, pk):
    proto = services.get_visible_protocol(request.user, pk)
    if proto is None:
        return _forbidden(request)
    label = (request.POST.get("label") or "").strip()
    href = (request.POST.get("href_template") or "").strip()
    if not label or not href:
        if is_htmx(request):
            return htmx_error("Shortcut label and href are required.")
        return HttpResponseBadRequest("Shortcut label and href are required.")
    order = int_or_none(request.POST.get("order")) or 0
    active = 1 if request.POST.get("active") else 0
    services.create_shortcut(
        request.user,
        protocol=proto,
        label=label,
        href_template=href,
        params_template=(request.POST.get("params_template") or "").strip(),
        order=order,
        active=active,
    )
    return _shortcut_refresh(request, proto, "Shortcut created.")


@ui3_login_required
@require_http_methods(["GET", "POST"])
def shortcut_edit(request, pk):
    sc = services.get_owned_shortcut(request.user, pk)
    if sc is None:
        return _forbidden(request, "Shortcut not found or not accessible.")
    proto = services.get_visible_protocol(request.user, sc.protocol_id) if sc.protocol_id else None
    if request.method == "GET":
        return render(request, "ui3/protocols/_shortcut_modal.html", {"shortcut": sc, "protocol": proto})
    label = (request.POST.get("label") or "").strip()
    href = (request.POST.get("href_template") or "").strip()
    if not label or not href:
        if is_htmx(request):
            return htmx_error("Shortcut label and href are required.")
        return HttpResponseBadRequest("Shortcut label and href are required.")
    sc.label = label
    sc.href_template = href
    sc.params_template = (request.POST.get("params_template") or "").strip()
    sc.order = int_or_none(request.POST.get("order")) or 0
    sc.active = 1 if request.POST.get("active") else 0
    sc.save()
    if proto is None:
        return _forbidden(request)
    return _shortcut_refresh(request, proto, "Shortcut updated.")


@ui3_login_required
@require_POST
def shortcut_delete(request, pk):
    sc = services.get_owned_shortcut(request.user, pk)
    if sc is None:
        return _forbidden(request, "Shortcut not found or not accessible.")
    proto = services.get_visible_protocol(request.user, sc.protocol_id) if sc.protocol_id else None
    sc.delete()
    if proto is None:
        return _forbidden(request)
    return _shortcut_refresh(request, proto, "Shortcut deleted.")


@ui3_login_required
@require_POST
def shortcut_toggle(request, pk):
    sc = services.get_owned_shortcut(request.user, pk)
    if sc is None:
        return _forbidden(request, "Shortcut not found or not accessible.")
    proto = services.get_visible_protocol(request.user, sc.protocol_id) if sc.protocol_id else None
    sc.active = 0 if sc.active else 1
    sc.save(update_fields=["active"])
    if proto is None:
        return _forbidden(request)
    return _shortcut_refresh(request, proto, "Shortcut {}.".format("enabled" if sc.active else "disabled."))
