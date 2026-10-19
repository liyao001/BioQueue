from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from QueueDB.models import Slave

from ..decorators import ui3_login_required
from ..http import htmx_error, is_htmx, list_params, querystring, render_htmx, with_toast
from .. import services


def _staff(request):
    return bool(getattr(request.user, "is_staff", False))


def _forbidden(request, message="Staff access required."):
    if is_htmx(request):
        return htmx_error(message, status=403)
    return HttpResponseForbidden(message)


def _runner_context(request):
    params = list_params(request)
    q = params.get("q") or ""
    runners = services.search_runners(q)
    page, paginator = services.paginate(runners, request, params=params)
    return {
        "page_obj": page,
        "paginator": paginator,
        "runners": page.object_list,
        "q": q,
        "filters": params,
        "qs": querystring(request),
        "page_size": page.paginator.per_page,
        "page_size_choices": (12, 24, 36, 48),
        "item_label": "runner",
    }


def _optional(request, name, limit):
    value = (request.POST.get(name) or "").strip()
    if len(value) > limit:
        return None, "{} is too long (max {} characters).".format(name.replace("_", " "), limit)
    return value, ""


def _runner_fields(request):
    """Parse a runner form. Returns (kwargs, error)."""
    name, err = _optional(request, "name", 100)
    if err:
        return None, err
    if not name:
        return None, "Name is required."
    try:
        cluster_manager = int(request.POST.get("cluster_manager") or "0")
    except (TypeError, ValueError):
        cluster_manager = 0
    # 0 runs on this machine. 1–4 are Slurm, LSF, Torque/PBS, and HTCondor.
    if cluster_manager not in (0, 1, 2, 3, 4):
        cluster_manager = 0
    ssh_host = (request.POST.get("ssh_connection") or "").strip()
    if cluster_manager not in (0, 1) and ssh_host:
        return None, (
            "Remote SSH is available for Slurm. Leave the SSH host blank so "
            "LSF, Torque/PBS, or HTCondor runs on this machine."
        )
    stage_raw = (request.POST.get("stage_in") or "").strip()
    if stage_raw == "":
        stage_in = None
    elif stage_raw in ("0", "1"):
        stage_in = int(stage_raw)
    else:
        return None, "Stage in must be inherit, off, or on."
    fields = {
        "name": name,
        "comment": request.POST.get("comment") or "",
        "cluster_manager": cluster_manager,
        "stage_in": stage_in,
    }
    for key, limit in (
        ("ssh_connection", 1024),
        ("ssh_user", 1024),
        ("ssh_key", 2048),
        ("cluster_manager_path", 2048),
        ("scripts_dir", 2048),
        ("result_root", 2048),
        ("log_root", 2048),
        ("workdir", 2048),
    ):
        value, err = _optional(request, key, limit)
        if err:
            return None, err
        fields[key] = value or None if key in ("ssh_connection", "ssh_user", "ssh_key", "cluster_manager_path") else value
    return fields, ""


def _apply(runner, fields):
    for key, value in fields.items():
        setattr(runner, key, value)


def _close_modal(response):
    close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
    response.content = response.content + close.encode("utf-8")
    return response


@ui3_login_required
@require_http_methods(["GET"])
def runner_list(request):
    if not _staff(request):
        return _forbidden(request)
    return render_htmx(request, "ui3/runners/list.html", "ui3/runners/_table.html", _runner_context(request))


@ui3_login_required
@require_POST
def runner_create(request):
    if not _staff(request):
        return _forbidden(request)
    fields, err = _runner_fields(request)
    if err:
        if is_htmx(request):
            return htmx_error(err)
        messages.error(request, err)
        return redirect("ui3:runners")
    runner = Slave(is_master=0)
    _apply(runner, fields)
    try:
        runner.save()
    except IntegrityError:
        message = "A runner with this name already exists."
        if is_htmx(request):
            return htmx_error(message)
        messages.error(request, message)
        return redirect("ui3:runners")
    if is_htmx(request):
        response = render(request, "ui3/runners/_table.html", _runner_context(request))
        return with_toast(response, "Runner created.")
    messages.success(request, "Runner created.")
    return redirect("ui3:runners")


@ui3_login_required
@require_http_methods(["GET", "POST"])
def runner_edit(request, pk):
    if not _staff(request):
        return _forbidden(request)
    runner = services.get_runner(pk)
    if runner is None:
        return _forbidden(request, "Runner not found.")
    if request.method == "GET":
        return render(request, "ui3/runners/_edit_modal.html", {"runner": runner})
    fields, err = _runner_fields(request)
    if err:
        if is_htmx(request):
            return htmx_error(err)
        messages.error(request, err)
        return redirect("ui3:runners")
    _apply(runner, fields)
    try:
        runner.save()
    except IntegrityError:
        message = "A runner with this name already exists."
        if is_htmx(request):
            return htmx_error(message)
        messages.error(request, message)
        return redirect("ui3:runners")
    if is_htmx(request):
        response = render(request, "ui3/runners/_table.html", _runner_context(request))
        return with_toast(_close_modal(response), "Runner updated.")
    messages.success(request, "Runner updated.")
    return redirect("ui3:runners")


@ui3_login_required
@require_POST
def runner_delete(request, pk):
    if not _staff(request):
        return _forbidden(request)
    runner = services.get_runner(pk)
    if runner is None:
        return _forbidden(request, "Runner not found.")
    assigned = services.runner_job_count(runner)
    if assigned:
        message = "Cannot delete runner '{}' because {} job{} still use it.".format(
            runner.name, assigned, "" if assigned == 1 else "s"
        )
        if is_htmx(request):
            return htmx_error(message)
        messages.error(request, message)
        return redirect("ui3:runners")
    name = runner.name
    runner.delete()
    if is_htmx(request):
        response = render(request, "ui3/runners/_table.html", _runner_context(request))
        return with_toast(_close_modal(response), "Runner '{}' deleted.".format(name))
    messages.success(request, "Runner '{}' deleted.".format(name))
    return redirect("ui3:runners")
