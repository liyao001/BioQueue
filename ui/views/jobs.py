import os

from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from QueueDB.models import JobStatus

from ..decorators import ui3_login_required
from ..files import (
    MAX_FILE_NAME,
    delete_job_file_tree,
    delete_job_files,
    download_response,
    history_tokens_to_archive_paths,
    listed_display_name,
    list_workspace_files,
    page_job_files,
    preview_mode_for,
    preview_response,
    preview_text,
    rename_job_file,
    resolve_listed_job_file,
    traces_to_archive_paths,
)
from ..http import (
    array_parent_from_request,
    combo_query,
    csv_ints,
    delegate_for,
    htmx_error,
    hx_redirect,
    int_or_none,
    is_htmx,
    list_params,
    querystring,
    render_htmx,
    toast_html,
    with_toast,
)
from .. import services


ADVANCED_KEYS = (
    "job_name_not",
    "protocol_name",
    "protocol_name_not",
    "workspace_name",
    "workspace_name_not",
    "parameter",
    "parameter_not",
    "input_file",
    "input_file_not",
    "status_not",
    "id_not",
    "mode",
)


def _job_list_context(request, extra_params=None):
    params = list_params(request)
    extra = dict(extra_params or {})
    array_pk = extra.get("parent_job")
    if array_pk is None:
        array_pk = array_parent_from_request(request)
        if array_pk is not None:
            extra["parent_job"] = array_pk
    if extra:
        params = params.copy()
        for key, value in extra.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = str(value)
    jobs = services.search_jobs(request.user, params)
    page, paginator = services.paginate(jobs, request, page_size=12, params=params)
    protocols = services.visible_protocols(request.user)
    workspaces = services.visible_workspaces(request.user)
    selected_status = csv_ints(params.get("status", ""))
    selected_status_not = csv_ints(params.get("status_not", ""))
    selected_visibility = [v for v in csv_ints(params.get("visibility", "")) if v in (0, 1, 2)]
    show_advanced = any((params.get(k) or "").strip() for k in ADVANCED_KEYS)
    auto_refresh = params.get("auto", "1") != "0"
    protocol_id = int_or_none(params.get("protocol"))
    workspace_id = int_or_none(params.get("workspace"))
    jobs = list(page.object_list)
    services.shortcuts_for_jobs(request.user, jobs)
    step_map = services.protocol_steps_by_parent([j.protocol_id for j in jobs])
    delegate = delegate_for(request.user)
    staff = bool(getattr(request.user, "is_staff", False))
    parent_job_obj = None
    parent_id = int_or_none(params.get("parent_job"))
    if parent_id:
        parent_job_obj = services.get_readable_job(request.user, parent_id)
    for job in jobs:
        if (getattr(job.protocol, "template", None) or "").strip():
            steps = services.runnable_steps(job)
            job.ui3_templated = True
        else:
            steps = step_map.get(job.protocol_id) or []
            job.ui3_templated = False
        job.ui3_step_total = len(steps)
        job.ui3_step_command = ""
        if job.status in (JobStatus.RUNNING, JobStatus.WRONG) and steps:
            idx = job.resume or 0
            if 0 <= idx < len(steps):
                job.ui3_step_command = services.step_command_preview(steps[idx])
        job.ui3_can_write = staff or job.user_id == getattr(delegate, "id", None)
    return {
        "page_obj": page,
        "paginator": paginator,
        "jobs": jobs,
        "protocols": protocols,
        "workspaces": workspaces,
        "selected_protocol": protocols.filter(pk=protocol_id).first() if protocol_id else None,
        "selected_workspace": workspaces.filter(pk=workspace_id).first() if workspace_id else None,
        "status_choices": JobStatus.choices,
        "visibility_choices": ((0, "Hidden"), (1, "Visible"), (2, "In workspace")),
        "selected_status": selected_status,
        "selected_status_not": selected_status_not,
        "selected_visibility": selected_visibility,
        "show_advanced": show_advanced,
        "auto_refresh": auto_refresh,
        "filters": params,
        "qs": querystring(request, **({"parent_job": array_pk} if array_pk is not None else {})),
        "status_badge": services.STATUS_BADGE,
        "array_parent_id": int_or_none(params.get("parent_job")),
        "array_parent": parent_job_obj,
        "mode": (params.get("mode") or "all"),
        "scope": (params.get("scope") or "own"),
        "page_size": page.paginator.per_page,
        "page_size_choices": (12, 24, 36, 48),
        "job_list_url": reverse("ui3:job_array", args=[int(array_pk)]) if array_pk is not None else reverse("ui3:jobs"),
        "array_page": array_pk is not None,
    }


@ui3_login_required
@require_http_methods(["GET"])
def job_list(request):
    ctx = _job_list_context(request)
    return render_htmx(request, "ui3/jobs/list.html", "ui3/jobs/_results.html", ctx)


@ui3_login_required
@require_http_methods(["GET"])
def running_count(request):
    count = services.running_job_count(request.user)
    label = "99+" if count > 99 else str(count)
    if count <= 0:
        return HttpResponse("")
    return render(request, "ui3/partials/running_badge.html", {"count": count, "label": label})


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_migrate(request):
    if not getattr(request.user, "is_staff", False):
        if is_htmx(request):
            return htmx_error("Staff access required.", status=403)
        return HttpResponseForbidden("Staff access required.")
    form = {
        "source": (request.POST.get("source") or request.GET.get("source") or "").strip(),
        "dest": (request.POST.get("dest") or request.GET.get("dest") or "").strip(),
        "ids": request.POST.get("ids") or request.GET.get("ids") or "",
        "move_files": True,
    }
    if request.method == "POST":
        form["move_files"] = request.POST.get("move_files") == "1"
    ctx = {"form": form, "result": None, "error": None}
    if request.method == "GET":
        return render(request, "ui3/jobs/migrate.html", ctx)
    dry_run = request.POST.get("dry_run") != "0"
    try:
        from_user = services.find_user(form["source"])
        to_user = services.find_user(form["dest"])
        if from_user is None:
            raise services.JobMigrateError("Source account not found.")
        if to_user is None:
            raise services.JobMigrateError("Destination account not found.")
        if not dry_run and request.POST.get("confirm") != "1":
            raise services.JobMigrateError("Confirm the migrate before running it.")
        result = services.migrate_jobs(
            from_user,
            to_user,
            services.parse_migrate_job_ids(form["ids"]),
            move_files=form["move_files"],
            dry_run=dry_run,
        )
    except services.JobMigrateError as exc:
        ctx["error"] = str(exc)
        if is_htmx(request):
            return htmx_error(ctx["error"])
        return render(request, "ui3/jobs/migrate.html", ctx, status=400)
    ctx["result"] = result
    if not dry_run:
        if result["errors"]:
            messages.error(
                request,
                "Migrate finished with {} error(s); {} job(s) moved.".format(
                    result["errors"], result["moved"]
                ),
            )
        elif result["moved"] == 0:
            messages.warning(request, "No jobs were migrated.")
        else:
            messages.success(
                request,
                "Migrated {} job(s) from {} to {}.".format(
                    result["moved"], from_user.username, to_user.username
                ),
            )
    return render(request, "ui3/jobs/migrate.html", ctx)


@ui3_login_required
@require_http_methods(["GET"])
def job_migrate_search(request):
    if not getattr(request.user, "is_staff", False):
        return JsonResponse({"detail": "Staff access required."}, status=403)
    source = (request.GET.get("source") or "").strip()
    from_user = None
    if source:
        try:
            from_user = services.find_user(source)
        except services.JobMigrateError:
            from_user = None
        if from_user is None:
            return JsonResponse({"results": []})
    return JsonResponse(
        {"results": services.search_migrate_jobs(from_user, request.GET.get("q") or "")}
    )


def _require_readable_job(request, pk):
    job = services.get_readable_job(request.user, pk)
    if job is None:
        return None, HttpResponseForbidden("Job not found or not accessible.")
    return job, None


def _require_writable_job(request, pk):
    job = services.get_writable_job(request.user, pk)
    if job is None:
        return None, HttpResponseForbidden("Job not found or not accessible.")
    return job, None


def _bad(request, message, status=400):
    if is_htmx(request):
        return htmx_error(message, status=status)
    return HttpResponseBadRequest(message)


def _new_job_base_context(request, *, tab="single", form=None, error=None, warning=None, clone=None, batch_result=None, array_result=None):
    protocols = services.visible_protocols(request.user)
    workspaces = services.visible_workspaces(request.user)
    form = form if form is not None else {}
    selected_protocol = None
    protocol_id = int_or_none(form.get("protocol") if hasattr(form, "get") else None)
    if protocol_id:
        selected_protocol = protocols.filter(pk=protocol_id).first()
        if selected_protocol is None:
            selected_protocol = services.get_usable_protocol(request.user, protocol_id)
    selected_workspace = None
    workspace_id = int_or_none(form.get("workspace") if hasattr(form, "get") else None)
    if workspace_id:
        selected_workspace = workspaces.filter(pk=workspace_id).first()
    # Ensure selected/clone protocol appears as a combo option even if outside default visibility.
    if selected_protocol is not None and not protocols.filter(pk=selected_protocol.pk).exists():
        from itertools import chain

        protocols = list(chain([selected_protocol], protocols))
    return {
        "protocols": protocols,
        "workspaces": workspaces,
        "selected_protocol": selected_protocol,
        "samples_active": bool(selected_protocol and (selected_protocol.template or "").strip()),
        "selected_workspace": selected_workspace,
        "clone": clone,
        "form": form,
        "error": error,
        "warning": warning,
        "tab": tab or "single",
        "batch_result": batch_result,
        "array_result": array_result,
        "token_list": services.autocomplete_tokens(request.user),
    }


def _resolve_workspace(request, workspaces, raw_id):
    """Return (workspace_or_None, warning_or_None). Invalid id → warning, no silent drop."""
    if raw_id in (None, ""):
        return None, None
    ws_id = int_or_none(raw_id)
    if ws_id is None:
        return None, "Invalid workspace id; job will be created without a workspace."
    workspace = workspaces.filter(pk=ws_id).first()
    if workspace is None:
        return None, "Workspace #{} was not found or is not accessible; job will be created without a workspace.".format(
            ws_id
        )
    return workspace, None


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_create(request):
    protocols = services.visible_protocols(request.user)
    workspaces = services.visible_workspaces(request.user)
    clone = None
    error = None
    warning = None
    clone_raw = request.GET.get("clone")
    clone_id = int_or_none(clone_raw)
    if clone_raw not in (None, "") and clone_id is None:
        error = "Invalid clone job id."
    elif clone_id:
        clone = services.get_readable_job(request.user, clone_id)
        if clone is None:
            error = "Clone job #{} was not found or is not accessible.".format(clone_id)
        else:
            proto = clone.protocol
            if proto is not None and not services.protocol_usable(request.user, proto):
                error = (
                    "Cannot clone job #{}: protocol #{} ({}) is not available for creating new jobs."
                ).format(clone.id, proto.id, proto.name or "")
                clone = None

    if request.method == "POST":
        name = (request.POST.get("job_name") or "").strip()
        protocol_id = int_or_none(request.POST.get("protocol"))
        protocol = services.get_usable_protocol(request.user, protocol_id) if protocol_id else None
        if not name or protocol is None:
            ctx = _new_job_base_context(
                request,
                tab="single",
                form=request.POST,
                error="Job name and protocol are required.",
                clone=clone,
            )
            return render(request, "ui3/jobs/new.html", ctx, status=400)
        workspace, ws_warning = _resolve_workspace(request, workspaces, request.POST.get("workspace"))
        if ws_warning and request.POST.get("workspace") not in (None, ""):
            # Reject invalid workspace rather than silently dropping when explicitly sent.
            ctx = _new_job_base_context(
                request,
                tab="single",
                form=request.POST,
                error=ws_warning.replace("; job will be created without a workspace.", "."),
                clone=clone,
            )
            return render(request, "ui3/jobs/new.html", ctx, status=400)
        array_setting = (request.POST.get("array_setting") or "").strip() or None
        sample_sheet = request.POST.get("sample_sheet") or ""
        try:
            sample_sheet = services.prepare_sample_sheet(protocol, request.POST.get("input_file") or "", sample_sheet)
        except services.ProtocolTemplateError as exc:
            ctx = _new_job_base_context(
                request,
                tab="single",
                form=request.POST,
                error=str(exc),
                clone=clone,
            )
            return render(request, "ui3/jobs/new.html", ctx, status=400)
        job = services.create_job(
            delegate_for(request.user),
            job_name=name,
            protocol=protocol,
            parameter=request.POST.get("parameter") or "",
            input_file=request.POST.get("input_file") or "",
            workspace=workspace,
            comments=request.POST.get("comments") or "",
            is_gpu_job=1 if request.POST.get("is_gpu_job") else 0,
            array_setting=array_setting,
            sample_sheet=sample_sheet,
        )
        messages.success(request, "Job #{} created.".format(job.id))
        return redirect("ui3:jobs")

    initial = {}
    if clone and error is None:
        initial = {
            "job_name": "{}-copy".format(clone.job_name or ""),
            "protocol": clone.protocol_id or "",
            "parameter": clone.parameter or "",
            "input_file": clone.input_file or "",
            "workspace": clone.workspace_id or "",
            "comments": clone.comments or "",
            "is_gpu_job": clone.is_gpu_job,
            "array_setting": clone.array_setting or "",
            "sample_sheet": clone.sample_sheet or "",
        }
        # Ensure clone protocol appears in options even if not in default visible set.
        if clone.protocol_id and protocols.filter(pk=clone.protocol_id).first() is None:
            if services.protocol_usable(request.user, clone.protocol):
                # Already usable (e.g. public); selected_protocol resolves via get_usable_protocol.
                pass
    ctx = _new_job_base_context(
        request,
        tab=request.GET.get("tab") or "single",
        form=initial,
        error=error,
        warning=warning,
        clone=clone if error is None else None,
    )
    return render(request, "ui3/jobs/new.html", ctx)


@ui3_login_required
@require_POST
def job_create_batch(request):
    workspaces = services.visible_workspaces(request.user)
    tsv_content = ""
    if request.FILES.get("file"):
        try:
            data = request.FILES["file"].read()
            tsv_content = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
        except Exception:
            ctx = _new_job_base_context(
                request,
                tab="bulkfile" if request.POST.get("tab") == "bulkfile" else "bulk",
                form=request.POST,
                error="Failed to read uploaded file.",
            )
            return render(request, "ui3/jobs/new.html", ctx, status=400)
    else:
        tsv_content = request.POST.get("tsv") or ""
    if not (tsv_content or "").strip():
        tab = "bulkfile" if request.FILES or request.POST.get("tab") == "bulkfile" else "bulk"
        ctx = _new_job_base_context(
            request,
            tab=tab,
            form=request.POST,
            error="No TSV provided.",
        )
        return render(request, "ui3/jobs/new.html", ctx, status=400)

    workspace, ws_warning = _resolve_workspace(request, workspaces, request.POST.get("workspace"))
    if ws_warning and request.POST.get("workspace") not in (None, ""):
        tab = "bulkfile" if request.FILES or request.POST.get("tab") == "bulkfile" else "bulk"
        ctx = _new_job_base_context(
            request,
            tab=tab,
            form=request.POST,
            error=ws_warning.replace("; job will be created without a workspace.", "."),
        )
        return render(request, "ui3/jobs/new.html", ctx, status=400)

    result = services.create_jobs_batch(delegate_for(request.user), tsv_content, workspace=workspace)
    tab = "bulkfile" if request.FILES or request.POST.get("tab") == "bulkfile" else "bulk"
    if result["created"]:
        messages.success(request, "Created {} job(s).".format(result["created"]))
    ctx = _new_job_base_context(
        request,
        tab=tab,
        form=request.POST,
        warning=None if result["created"] else "No jobs were created.",
        batch_result=result,
    )
    status_code = 200 if result["created"] else 400
    return render(request, "ui3/jobs/new.html", ctx, status=status_code)


@ui3_login_required
@require_POST
def job_create_array(request):
    workspaces = services.visible_workspaces(request.user)
    name = (request.POST.get("job_name") or "").strip()
    protocol_id = int_or_none(request.POST.get("protocol"))
    protocol = services.get_usable_protocol(request.user, protocol_id) if protocol_id else None
    job_list = request.POST.get("job_list") or ""
    if not name or protocol is None or not job_list.strip():
        ctx = _new_job_base_context(
            request,
            tab="array",
            form=request.POST,
            error="Job name, protocol, and job list are required.",
        )
        return render(request, "ui3/jobs/new.html", ctx, status=400)
    workspace, ws_warning = _resolve_workspace(request, workspaces, request.POST.get("workspace"))
    if ws_warning and request.POST.get("workspace") not in (None, ""):
        ctx = _new_job_base_context(
            request,
            tab="array",
            form=request.POST,
            error=ws_warning.replace("; job will be created without a workspace.", "."),
        )
        return render(request, "ui3/jobs/new.html", ctx, status=400)
    result = services.create_array_job(
        delegate_for(request.user),
        protocol=protocol,
        job_name=name,
        job_list=job_list,
        workspace=workspace,
        is_gpu_job=1 if request.POST.get("is_gpu_job") else 0,
    )
    msg = "Array parent #{} created with {} child job(s).".format(result["parent"].id, result["created"])
    if result.get("errors"):
        messages.warning(request, msg + " Some lines were skipped.")
    else:
        messages.success(request, msg)
    ctx = _new_job_base_context(
        request,
        tab="array",
        form=request.POST,
        array_result=result,
        warning="Some child lines were skipped." if result.get("errors") else None,
    )
    return render(request, "ui3/jobs/new.html", ctx)


@ui3_login_required
@require_http_methods(["GET"])
def sample_scaffold(request):
    protocol = services.get_usable_protocol(request.user, int_or_none(request.GET.get("protocol")))
    try:
        context = services.sample_scaffold(protocol, request.GET.get("input_file", ""))
    except (services.ProtocolTemplateError, ValueError, TypeError):
        context = {
            "samples_active": bool(protocol and protocol.template),
            "samples_value": "",
            "samples_required": "",
            "samples_error": "",
            "samples_summary": "",
            "samples_files": "",
            "samples_hold": False,
        }
    context["force"] = request.GET.get("force") == "1"
    return render(request, "ui3/jobs/_sample_scaffold.html", context)


@ui3_login_required
@require_http_methods(["GET"])
def parameter_scaffold(request):
    protocol_id = int_or_none(request.GET.get("protocol"))
    protocol = services.get_usable_protocol(request.user, protocol_id) if protocol_id else None
    try:
        value = services.parameter_scaffold(
            protocol, request.user,
            input_file=request.GET.get("input_file", ""),
            sample_sheet=request.GET.get("sample_sheet", ""),
            legacy=(request.GET.get("legacy") or "").lower() in ("1", "true", "yes"),
        )
    except services.ProtocolTemplateError:
        # Input groups and JSON are often incomplete while the user types.
        return HttpResponse(status=204)
    if request.GET.get("format") == "text":
        return HttpResponse(value, content_type="text/plain; charset=utf-8")
    force = (request.GET.get("force") or "").lower() in ("1", "true", "yes")
    return render(request, "ui3/jobs/_parameter_scaffold.html", {"value": value, "force": force})


@ui3_login_required
@require_http_methods(["GET"])
def workspace_uploads(request):
    items = list_workspace_files(delegate_for(request.user), kind="uploads")
    q = (request.GET.get("q") or "").strip().lower()
    if q:
        items = [it for it in items if q in str(it.get("name", "")).lower()]
    return render(
        request,
        "ui3/jobs/_uploads_modal.html",
        {"items": items, "q": request.GET.get("q") or "", "target_id": request.GET.get("target") or "id_input_file"},
    )


@ui3_login_required
@require_http_methods(["GET"])
def job_results_picker(request):
    q = (request.GET.get("q") or "").strip()
    if q.isdigit():
        params = {"id": q, "scope": "own"}
    elif q:
        params = {"job_name": q, "scope": "own"}
    else:
        # Default: recent own jobs so the modal is usable without typing first.
        params = {"scope": "own"}
    own_jobs = list(services.search_jobs(request.user, params)[:20])
    shared_jobs = list(services.shared_search_jobs(request.user, q, limit=20))
    selected_job = None
    job_id = int_or_none(request.GET.get("job"))
    files_page = None
    is_shared = False
    if job_id:
        selected_job = services.get_readable_job(request.user, job_id)
        if selected_job is None:
            return _bad(request, "Job not found or not accessible.", status=404)
        delegate = delegate_for(request.user)
        is_shared = selected_job.user_id != getattr(delegate, "id", None)
        files_page = page_job_files(
            selected_job,
            q=request.GET.get("fq") or "",
            sort="name",
            order="asc",
            limit=request.GET.get("limit") or 50,
            offset=request.GET.get("offset") or 0,
        )
    return render(
        request,
        "ui3/jobs/_results_picker_modal.html",
        {
            "q": q,
            "own_jobs": own_jobs,
            "shared_jobs": shared_jobs,
            "selected_job": selected_job,
            "files_page": files_page,
            "is_shared": is_shared,
            "target_id": request.GET.get("target") or "id_input_file",
            "fq": request.GET.get("fq") or "",
        },
    )


def _refresh_or_row(request, job, message, level="success"):
    if is_htmx(request):
        ctx = _job_list_context(request)
        response = render(request, "ui3/jobs/_results.html", ctx)
        return with_toast(response, message, level)
    messages.add_message(request, messages.SUCCESS if level == "success" else messages.ERROR, message)
    array_pk = array_parent_from_request(request)
    if array_pk is not None:
        return redirect("ui3:job_array", array_pk)
    return redirect("ui3:jobs")


@ui3_login_required
@require_POST
def job_rerun(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    insitu = bool(int_or_none(request.POST.get("insitu")) or 0)
    if not insitu:
        services.maybe_delete_job_files(job)
    job.rerun_job(insitu=insitu)
    job.refresh_from_db()
    return _refresh_or_row(request, job, "Job #{} queued to rerun.".format(job.id))


@ui3_login_required
@require_POST
def job_terminate(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    job.terminate_job()
    job.refresh_from_db()
    return _refresh_or_row(request, job, "Job #{} terminate requested.".format(job.id))


@ui3_login_required
@require_POST
def job_lock(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    locked_param = request.POST.get("locked")
    if locked_param is None:
        job.locked = 0 if job.locked else 1
    else:
        job.locked = 1 if int(locked_param) else 0
    job.save(update_fields=["locked"])
    services.audit_operation(job, "Locked" if job.locked else "Unlocked")
    msg = "Job #{} locked.".format(job.id) if job.locked else "Job #{} unlocked.".format(job.id)
    return _refresh_or_row(request, job, msg)


@ui3_login_required
@require_POST
def job_visibility(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    vis = int_or_none(request.POST.get("visibility"))
    if vis not in (0, 1, 2):
        return _bad(request, "Invalid visibility.")
    if vis > 1 and job.workspace is None:
        return _bad(
            request,
            "Please assign a workspace to the job before setting visibility higher than 'workspace-only'.",
        )
    old_vis = job.visibility
    job.visibility = vis
    job.save(update_fields=["visibility"])
    services.audit_operation(job, "Changed visibility", comment="{} -> {}".format(old_vis, vis))
    labels = {0: "hidden", 1: "visible", 2: "visible in workspace"}
    return _refresh_or_row(request, job, "Job #{} is {}.".format(job.id, labels[vis]))


@ui3_login_required
@require_POST
def job_gpu(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked or job.status == JobStatus.RUNNING:
        return _bad(request, "Cannot change GPU flag while locked or running.")
    job.is_gpu_job = 0 if job.is_gpu_job else 1
    job.save(update_fields=["is_gpu_job"])
    return _refresh_or_row(
        request,
        job,
        "Job #{} marked as {} job.".format(job.id, "GPU" if job.is_gpu_job else "CPU"),
    )


@ui3_login_required
@require_POST
def job_mark_finished(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    try:
        services.mark_job_finished(job)
    except services.JobActionError as exc:
        return _bad(request, str(exc))
    job.refresh_from_db()
    return _refresh_or_row(request, job, "Job #{} marked finished.".format(job.id))


@ui3_login_required
@require_GET
def mark_finished_compat(request):
    """Legacy ``/ui/mark-finished?job_id=``.

    Scripts still get the old JSON body. HTMX / browser navigations refresh or
    redirect like other job-card actions instead of dumping JSON in a tab.
    """
    job_id = int_or_none(request.GET.get("job_id") or request.GET.get("job"))
    wants_json = "application/json" in (request.headers.get("Accept") or "").lower()

    def _json(payload, status=200):
        return JsonResponse(payload, status=status)

    if job_id is None:
        if is_htmx(request):
            return _bad(request, "job_id is required.")
        if not wants_json and "text/html" in (request.headers.get("Accept") or "").lower():
            messages.error(request, "job_id is required.")
            return redirect("ui3:jobs")
        return _json(
            {"msg_title": "error", "info": "job_id is required.", "url": ".", "status": 0, "wait_second": 3},
            status=400,
        )
    job = services.get_writable_job(request.user, job_id)
    if job is None:
        if is_htmx(request):
            return _bad(request, "Job not found or not accessible.", status=403)
        if not wants_json and "text/html" in (request.headers.get("Accept") or "").lower():
            messages.error(request, "Job not found or not accessible.")
            return redirect("ui3:jobs")
        return _json(
            {"msg_title": "error", "info": "Job not found or not accessible.", "url": ".", "status": 0, "wait_second": 3},
            status=403,
        )
    try:
        services.mark_job_finished(job)
    except services.JobActionError as exc:
        if is_htmx(request):
            return _bad(request, str(exc))
        if not wants_json and "text/html" in (request.headers.get("Accept") or "").lower():
            messages.error(request, str(exc))
            return redirect("ui3:jobs")
        return _json(
            {"msg_title": "error", "info": str(exc), "url": ".", "status": 0, "wait_second": 3},
            status=400,
        )
    job.refresh_from_db()
    if is_htmx(request):
        return _refresh_or_row(request, job, "Job #{} marked finished.".format(job.id))
    if not wants_json and "text/html" in (request.headers.get("Accept") or "").lower():
        messages.success(request, "Job #{} marked finished.".format(job.id))
        return redirect("ui3:jobs")
    return _json({"msg_title": "success", "info": "Marked", "url": ".", "status": 1, "wait_second": 1})


@ui3_login_required
@require_POST
def job_mark_wrong(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    try:
        services.mark_job_wrong(job)
    except services.JobActionError as exc:
        return _bad(request, str(exc))
    job.refresh_from_db()
    return _refresh_or_row(request, job, "Job #{} marked failed.".format(job.id))


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_resume(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    n_steps = len(services.runnable_steps(job))
    max_step = max(0, n_steps - 1) if n_steps else 0
    if request.method == "GET":
        return render(
            request,
            "ui3/jobs/_resume_modal.html",
            {"job": job, "n_steps": n_steps, "max_step": max_step, "current": job.resume or 0},
        )
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    if request.POST.get("from_failed") == "1":
        if job.status != JobStatus.WRONG:
            return _bad(request, "Resume from failed step is only for failed jobs.")
        try:
            services.resume_job_from(job, rollback_to=None)
        except services.JobActionError as exc:
            return _bad(request, str(exc))
    else:
        rollback = int_or_none(request.POST.get("rollback_to")) or 0
        try:
            services.resume_job_from(job, rollback_to=rollback)
        except services.JobActionError as exc:
            return _bad(request, str(exc))
    job.refresh_from_db()
    if is_htmx(request):
        ctx = _job_list_context(request)
        response = render(request, "ui3/jobs/_results.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Job #{} resumed from step {}.".format(job.id, job.resume))
    return _refresh_or_row(request, job, "Job #{} resumed from step {}.".format(job.id, job.resume))


@ui3_login_required
@require_POST
def job_delete(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    n_archive = services.job_has_archives(job)
    if n_archive > 0:
        return _bad(request, "Job is under protection ({} dependent archives).".format(n_archive))
    job_id = job.id
    services.audit_operation(job, "Deleted a job")
    job.delete()
    # In-memory job still holds run_dir/user_id/result for filesystem cleanup.
    services.maybe_delete_job_files(job)
    if is_htmx(request):
        ctx = _job_list_context(request)
        response = render(request, "ui3/jobs/_results.html", ctx)
        return with_toast(response, "Job #{} deleted.".format(job_id))
    messages.success(request, "Job #{} deleted.".format(job_id))
    return redirect("ui3:jobs")


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_edit_field(request, pk, field):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    allowed = {
        "parameter": "parameter",
        "input_file": "input_file",
        "comments": "comments",
        "array_setting": "array_setting",
        "sample_sheet": "sample_sheet",
    }
    if field not in allowed:
        return _bad(request, "Unknown field.")
    attr = allowed[field]
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    if request.method == "GET":
        return render(
            request,
            "ui3/jobs/_edit_modal.html",
            {
                "job": job,
                "field": field,
                "value": getattr(job, attr) or "",
                "title": field.replace("_", " "),
                "token_list": services.autocomplete_tokens(request.user) if field in ("parameter", "input_file") else [],
            },
        )
    value = request.POST.get("value") or ""
    if field == "sample_sheet":
        try:
            value = services.prepare_sample_sheet(job.protocol, job.input_file or "", value)
        except services.ProtocolTemplateError as exc:
            return _bad(request, str(exc))
        job.sample_sheet = value
        job.save(update_fields=["sample_sheet"])
        services.audit_operation(job, "Changed sample sheet", comment=value)
    elif field == "parameter":
        job.update_parameter(value)
    elif field == "input_file":
        job.update_inputs(value)
    elif field == "array_setting":
        setting = value.strip()
        if len(setting) > 100:
            return _bad(request, "Array setting is too long (max 100 characters).")
        job.array_setting = setting or None
        job.save(update_fields=["array_setting"])
        services.audit_operation(job, "Changed array setting", comment=job.array_setting or "")
    else:
        job.update_comments(value)
    job.refresh_from_db()
    if is_htmx(request):
        ctx = _job_list_context(request)
        response = render(request, "ui3/jobs/_results.html", ctx)
        close = (
            '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
            '<div id="picker-root" hx-swap-oob="innerHTML"></div>'
        )
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, "Job #{} {} updated.".format(job.id, field.replace("_", " ")))
    messages.success(request, "Updated.")
    return redirect("ui3:jobs")


@ui3_login_required
@require_http_methods(["GET"])
def job_logs(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    kind = (request.GET.get("kind") or request.GET.get("type") or "stdout").lower()
    text = ""
    try:
        import os

        from worker.bases import get_config, get_job_log

        suffix = ".log" if kind in ("stdout", "out") else ".err"
        log_dir = get_config("env", "log")
        if not log_dir:
            text = "(log unavailable: log directory is not configured)"
        else:
            log_path = os.path.join(log_dir, "{}{}".format(job.id, suffix))
            if not os.path.exists(log_path):
                text = "(log file not found: {})".format(log_path)
            else:
                text = get_job_log(log_path) or ""
                text = text.replace("<br />", "\n").replace("<br/>", "\n")
    except Exception as exc:
        text = "(log unavailable: {})".format(exc)
    return render(request, "ui3/jobs/_log_modal.html", {"job": job, "kind": kind, "text": text})


@ui3_login_required
@require_http_methods(["GET"])
def job_history(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    items = services.job_history(job)
    return render(
        request,
        "ui3/jobs/_history_modal.html",
        {"job": job, "items": items, "status_badge": services.STATUS_BADGE},
    )


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_rename(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if request.method == "GET":
        return render(request, "ui3/jobs/_rename_modal.html", {"job": job})
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    new_name = (request.POST.get("new_name") or "").strip()
    if not new_name:
        return _bad(request, "new_name is required")
    dry_run = bool(int_or_none(request.POST.get("dry_run")) or 0)
    try:
        result = services.rename_job(job, new_name, dry_run=dry_run)
    except Exception as exc:
        return _bad(request, str(exc))
    if result.get("conflicts"):
        return _bad(request, "Rename conflicts: {}".format(len(result["conflicts"])), status=409)
    job.refresh_from_db()
    if dry_run:
        msg = "Dry run OK for job #{} ({} renames).".format(job.id, len(result.get("renames") or []))
    else:
        msg = "Job #{} renamed to {}.".format(job.id, new_name)
    if is_htmx(request):
        ctx = _job_list_context(request)
        response = render(request, "ui3/jobs/_results.html", ctx)
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, msg)
    return _refresh_or_row(request, job, msg)


@ui3_login_required
@require_http_methods(["GET"])
def job_dependents(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    depth = int_or_none(request.GET.get("depth")) or 1
    related = services.find_dependents(request.user, job, depth=depth)
    return render(
        request,
        "ui3/jobs/_relations_modal.html",
        {
            "job": job,
            "related": related,
            "title": "Dependents of job #{}".format(job.id),
            "relation": "dependents",
            "status_badge": services.STATUS_BADGE,
        },
    )


@ui3_login_required
@require_http_methods(["GET"])
def job_dependencies(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    related = services.find_dependencies(request.user, job)
    return render(
        request,
        "ui3/jobs/_relations_modal.html",
        {
            "job": job,
            "related": related,
            "title": "Dependencies of job #{}".format(job.id),
            "relation": "dependencies",
            "status_badge": services.STATUS_BADGE,
        },
    )


@ui3_login_required
@require_POST
def job_bulk(request):
    action = (request.POST.get("action") or "").strip()
    allowed = {"terminate", "rerun_clean", "rerun_insitu", "delete", "compare", "purge"}
    if action not in allowed:
        return _bad(request, "Invalid bulk action.")
    raw_ids = request.POST.getlist("ids") or request.POST.getlist("ids[]")
    if len(raw_ids) == 1 and ("," in raw_ids[0] or " " in raw_ids[0]):
        ids = csv_ints(raw_ids[0])
    else:
        ids = []
        for token in raw_ids:
            ids.extend(csv_ints(token))
        if not ids and request.POST.get("ids"):
            ids = csv_ints(request.POST.get("ids"))
    # unique preserve order
    seen = set()
    ordered = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    ids = ordered
    if not ids:
        return _bad(request, "No job ids provided.")

    if action == "compare":
        if len(ids) != 2:
            return _bad(request, "Select exactly two jobs to compare.")
        left = services.get_readable_job(request.user, ids[0])
        right = services.get_readable_job(request.user, ids[1])
        if left is None or right is None:
            return _bad(request, "One or both jobs are not accessible.", status=403)
        url = reverse("ui3:job_compare_pair", args=[left.id, right.id])
        if is_htmx(request):
            return hx_redirect(url)
        return redirect(url)

    done = 0
    skipped_locked = 0
    skipped_other = 0
    for pk in ids:
        job = services.get_writable_job(request.user, pk)
        if job is None:
            skipped_other += 1
            continue
        if action != "terminate" and job.locked:
            skipped_locked += 1
            continue
        try:
            if action == "terminate":
                job.terminate_job()
                done += 1
            elif action == "rerun_clean":
                services.maybe_delete_job_files(job)
                job.rerun_job(insitu=0)
                done += 1
            elif action == "rerun_insitu":
                job.rerun_job(insitu=1)
                done += 1
            elif action == "delete":
                if services.job_has_archives(job) > 0:
                    skipped_other += 1
                    continue
                services.audit_operation(job, "Deleted a job")
                job.delete()
                services.maybe_delete_job_files(job)
                done += 1
            elif action == "purge":
                if services.job_has_archives(job) > 0:
                    skipped_other += 1
                    continue
                delete_job_file_tree(job)
                services.audit_operation(job, "Purged job result files")
                done += 1
        except Exception:
            skipped_other += 1

    parts = ["Bulk {}: {} job(s).".format(action, done)]
    if skipped_locked:
        parts.append("Skipped {} locked.".format(skipped_locked))
    if skipped_other:
        parts.append("Skipped {} other.".format(skipped_other))
    message = " ".join(parts)
    if is_htmx(request):
        ctx = _job_list_context(request)
        response = render(request, "ui3/jobs/_results.html", ctx)
        return with_toast(response, message)
    messages.success(request, message)
    return redirect("ui3:jobs")


@ui3_login_required
@require_http_methods(["GET"])
def protocol_options(request):
    items = list(
        services.filter_named_choices(
            services.visible_protocols(request.user),
            combo_query(request),
            extra_fields=("description",),
        )
    )
    empty_label = (request.GET.get("empty") or "").strip() or "Protocol: all"
    # Optionally pin a selected protocol id that must appear (e.g. clone / staff).
    pin_id = int_or_none(request.GET.get("pin"))
    if pin_id and not any(getattr(i, "id", None) == pin_id for i in items):
        pinned = services.get_usable_protocol(request.user, pin_id)
        if pinned is not None:
            items = [pinned] + items
    return render(
        request,
        "ui3/jobs/_combo_options.html",
        {"items": items, "empty_label": empty_label, "kind": "protocol"},
    )


@ui3_login_required
@require_http_methods(["GET"])
def workspace_options(request):
    items = services.filter_named_choices(services.assignable_workspaces(request.user), combo_query(request))
    empty_label = (request.GET.get("empty") or "").strip() or "Workspace: all"
    return render(
        request,
        "ui3/jobs/_combo_options.html",
        {"items": items, "empty_label": empty_label, "kind": "workspace"},
    )


@ui3_login_required
@require_http_methods(["GET"])
def runner_options(request):
    items = services.filter_named_choices(services.assignable_runners(request.user), combo_query(request))
    empty_label = (request.GET.get("empty") or "").strip() or "(none)"
    return render(
        request,
        "ui3/jobs/_combo_options.html",
        {"items": items, "empty_label": empty_label, "kind": "runner"},
    )


@ui3_login_required
@require_POST
def job_workspace(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    raw = (request.POST.get("value") or "").strip()
    if not raw:
        job.workspace = None
    else:
        ws_id = int_or_none(raw)
        ws = services.assignable_workspaces(request.user).filter(pk=ws_id).first() if ws_id else None
        if ws is None:
            return _bad(request, "Workspace not found.")
        job.workspace = ws
    job.save(update_fields=["workspace"])
    services.audit_operation(job, "Changed workspace", comment=str(job.workspace_id or ""))
    return _refresh_or_row(request, job, "Job #{} workspace updated.".format(job.id))


@ui3_login_required
@require_POST
def job_runner(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    raw = (request.POST.get("value") or "").strip()
    if not raw:
        job.slave = None
    else:
        runner_id = int_or_none(raw)
        runner = services.assignable_runners(request.user).filter(pk=runner_id).first() if runner_id else None
        if runner is None:
            return _bad(request, "Runner not found.")
        job.slave = runner
    job.save(update_fields=["slave"])
    services.audit_operation(job, "Changed runner", comment=str(job.slave_id or ""))
    return _refresh_or_row(request, job, "Job #{} runner updated.".format(job.id))


def _files_context(request, job):
    sort = request.GET.get("sort") or "name"
    order = request.GET.get("order") or "asc"
    sort_key = (request.GET.get("sort_key") or "").strip()
    if ":" in sort_key:
        key_sort, key_order = sort_key.split(":", 1)
        if key_sort:
            sort = key_sort
        if key_order:
            order = key_order
    page = page_job_files(
        job,
        q=request.GET.get("q") or "",
        sort=sort,
        order=order,
        limit=request.GET.get("limit") or 50,
        offset=request.GET.get("offset") or 0,
    )
    page["job"] = job
    delegate = delegate_for(request.user)
    staff = bool(getattr(request.user, "is_staff", False))
    job.ui3_can_write = staff or job.user_id == getattr(delegate, "id", None)
    return page


@ui3_login_required
@require_http_methods(["GET"])
def job_files(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    ctx = _files_context(request, job)
    partial = (request.GET.get("partial") or "").strip().lower()
    if partial == "rows":
        template = "ui3/jobs/_files_rows_append.html"
    elif partial:
        template = "ui3/jobs/_files_table.html"
    else:
        template = "ui3/jobs/_files_modal.html"
    return render(request, template, ctx)


@ui3_login_required
@require_http_methods(["GET"])
def job_file_download(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    trace = request.GET.get("trace")
    if not trace:
        return _bad(request, "trace is required")
    return download_response(job, trace)


@ui3_login_required
@require_http_methods(["GET"])
@xframe_options_exempt
def job_file_preview(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    trace = request.GET.get("trace")
    if not trace:
        return _bad(request, "trace is required")
    if request.GET.get("raw"):
        return preview_response(job, trace)
    name = request.GET.get("name") or listed_display_name(job, trace) or ""
    mode = preview_mode_for(name)
    text = ""
    if mode == "text":
        try:
            text = preview_text(job, trace)
        except Exception as exc:
            return _bad(request, str(exc), status=404)
    return render(
        request,
        "ui3/jobs/_preview_modal.html",
        {
            "job": job,
            "trace": trace,
            "name": name,
            "mode": mode,
            "text": text,
            "q": request.GET.get("q") or "",
            "sort": request.GET.get("sort") or "name",
            "order": request.GET.get("order") or "asc",
        },
    )


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_file_rename(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    trace = request.POST.get("trace") or request.GET.get("trace")
    if not trace:
        return _bad(request, "trace is required")
    path = resolve_listed_job_file(job, trace)
    if not path:
        return _bad(request, "File not found.", status=404)
    display = listed_display_name(job, trace) or os.path.basename(path)
    basename = os.path.basename(path)
    folder_label = os.path.dirname(display).replace("\\", "/")
    ctx = {
        "job": job,
        "trace": trace,
        "name": display,
        "basename": basename,
        "folder_label": folder_label,
        "max_name": MAX_FILE_NAME,
        "q": request.GET.get("q") or request.POST.get("q") or "",
        "sort": request.GET.get("sort") or request.POST.get("sort") or "name",
        "order": request.GET.get("order") or request.POST.get("order") or "asc",
    }
    if request.method == "GET":
        return render(request, "ui3/jobs/_files_rename_modal.html", ctx)
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    ok, detail = rename_job_file(job, trace, request.POST.get("new_name") or "")
    if not ok:
        status = 409 if "already exists" in (detail or "") else 400
        if detail == "File not found.":
            status = 404
        return _bad(request, detail, status=status)
    files_ctx = _files_context(request, job)
    response = render(request, "ui3/jobs/_files_modal.html", files_ctx)
    return with_toast(response, "Renamed to {}.".format(detail))


@ui3_login_required
@require_POST
def job_file_delete(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    traces = [t for t in request.POST.getlist("trace") if (t or "").strip()]
    traces.extend(t for t in request.POST.getlist("traces") if (t or "").strip())
    if not traces:
        one = (request.GET.get("trace") or "").strip()
        if one:
            traces = [one]
    if not traces:
        return _bad(request, "Select at least one file.")
    result = delete_job_files(job, traces)
    if result["requested"] == 0 or result["deleted"] == 0:
        return _bad(request, "Unable to delete file" if result["requested"] <= 1 else "Unable to delete selected files")
    ctx = _files_context(request, job)
    response = render(request, "ui3/jobs/_files_table.html", ctx)
    if result["deleted"] == 1 and result["failed"] == 0:
        msg = "File deleted."
    else:
        msg = "Deleted {} file{}.".format(result["deleted"], "" if result["deleted"] == 1 else "s")
        if result["failed"]:
            msg += " {} could not be deleted.".format(result["failed"])
    return with_toast(response, msg)


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_compare(request, pk, other=None):
    left, err = _require_readable_job(request, pk)
    if err:
        return err
    other_id = other if other is not None else int_or_none(request.GET.get("other") or request.POST.get("other"))
    if other_id is None:
        return render(request, "ui3/jobs/_compare_modal.html", {"job": left})
    if other_id == left.id:
        return _bad(request, "Choose a different job to compare.")
    right, err = _require_readable_job(request, other_id)
    if err:
        return err
    if other is None:
        url = reverse("ui3:job_compare_pair", args=[left.id, right.id])
        if is_htmx(request):
            return hx_redirect(url)
        return redirect(url)
    ctx = services.compare_jobs(left, right)
    ctx.update({"left": left, "right": right})
    return render(request, "ui3/jobs/compare.html", ctx)


@ui3_login_required
@require_http_methods(["GET"])
def job_protocol_diff(request, pk):
    job, err = _require_readable_job(request, pk)
    if err:
        return err
    if job.protocol_id is None:
        return _bad(request, "This job has no protocol.")
    ctx = services.compare_job_to_protocol(job)
    ctx["job"] = job
    return render(request, "ui3/jobs/protocol_diff.html", ctx)


@ui3_login_required
@require_POST
def job_purge(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if job.locked:
        return _bad(request, "This job is locked, please unlock first.")
    n_archive = services.job_has_archives(job)
    if n_archive > 0:
        return _bad(request, "Job is under protection ({} dependent archives).".format(n_archive))
    delete_job_file_tree(job)
    services.audit_operation(job, "Purged job result files")
    return _refresh_or_row(request, job, "Purged result files for job #{}.".format(job.id))


@ui3_login_required
@require_http_methods(["GET"])
def job_array_children(request, pk):
    parent, err = _require_readable_job(request, pk)
    if err:
        return err
    ctx = _job_list_context(request, extra_params={"parent_job": pk})
    ctx["array_page"] = True
    ctx["array_parent"] = parent
    ctx["array_parent_id"] = parent.id
    ctx["job_list_url"] = reverse("ui3:job_array", args=[parent.id])
    return render_htmx(request, "ui3/jobs/list.html", "ui3/jobs/_results.html", ctx)


@ui3_login_required
@require_http_methods(["GET", "POST"])
def job_archive(request, pk):
    job, err = _require_writable_job(request, pk)
    if err:
        return err
    if request.method == "GET":
        return render(request, "ui3/jobs/_archive_modal.html", {"job": job})
    description = (request.POST.get("description") or "").strip()
    shared_with = (request.POST.get("shared_with") or "").strip()
    if len(description) > 500:
        return _bad(request, "Description is too long (max 500 characters).")
    if len(shared_with) > 500:
        return _bad(request, "Shared-with list is too long (max 500 characters).")
    if not services.valid_share_list(shared_with):
        return _bad(request, "Shared-with must be a comma-separated list of email addresses.")
    traces = request.POST.getlist("traces") or request.POST.getlist("traces[]")
    raw_files = (request.POST.get("raw_files") or request.POST.get("input_files") or "").strip()
    if traces:
        paths, tokens = traces_to_archive_paths(job, traces)
        raw_files = ";".join(tokens)
        if not paths:
            return _bad(request, "No selected files could be resolved.")
    else:
        job, paths, error = history_tokens_to_archive_paths(request.user, raw_files, expected_job=job)
        if error:
            return _bad(request, error)
    archive, error = services.create_file_archive(
        request.user,
        job,
        paths,
        raw_files=raw_files,
        description=description,
        shared_with=shared_with,
    )
    if error:
        return _bad(request, error)
    message = "Archive #{} queued.".format(archive.id)
    if is_htmx(request):
        close = '<div id="modal-root" hx-swap-oob="innerHTML"></div>'
        target = (request.headers.get("HX-Target") or "").strip().lstrip("#")
        if target == "toast-root":
            response = HttpResponse(toast_html(message))
            response.content = response.content + close.encode("utf-8")
            return response
        ctx = _job_list_context(request)
        response = render(request, "ui3/jobs/_results.html", ctx)
        response.content = response.content + close.encode("utf-8")
        return with_toast(response, message)
    messages.success(request, message)
    return redirect("ui3:archives")
