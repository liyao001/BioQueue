"""JSON API for agents at ``/api/v1/``.

Authentication is ``Authorization: Bearer <api_key>``. The key is the account
profile's ``api_key``, shown on the Account page. A session cookie is not
accepted: these views are CSRF-exempt, and a cookie would let another site
submit jobs while the owner is signed in.

POST endpoints accept an ``Idempotency-Key`` header. The same account, key, and
body replay the first response. The same key with a different body is a 409.
"""

import hashlib
import hmac
import json
import os
import secrets
from datetime import timedelta
from functools import wraps

from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from QueueDB.models import ApiIdempotency, JobStatus, Profile

from . import services
from .files import page_job_files
from .http import delegate_for

MAX_LOG_CHARS = 512_000
MAX_IDEMPOTENCY_BODY = 1_000_000
IDEMPOTENCY_STALE = timedelta(seconds=120)
PROTOCOL_LIST_LIMIT = 500
AUTH_ERROR = "Send Authorization: Bearer <api_key>. The key is on the Account page."

JOB_FIELDS = {
    "job_name",
    "protocol",
    "parameter",
    "input_file",
    "workspace",
    "comments",
    "is_gpu_job",
    "array_setting",
    "sample_sheet",
    "runner",
}
BATCH_FIELDS = {"tsv", "workspace"}


class AgentInputError(ValueError):
    """A request the agent can fix by changing the JSON."""


def error(message, status):
    return JsonResponse({"error": message}, status=status)


def authenticate_bearer(request):
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() not in ("bearer", "token") or not token:
        return None
    profile = Profile.objects.select_related("user").filter(api_key=token).first()
    if profile is None or profile.user is None or not profile.user.is_active:
        return None
    if not hmac.compare_digest(str(profile.api_key), token):
        return None
    return profile.user


def agent_api(view):
    """Require a bearer token. Replay a finished POST when Idempotency-Key matches."""

    @csrf_exempt
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = authenticate_bearer(request)
        if user is None:
            return error(AUTH_ERROR, 401)
        request.agent_user = user
        key = (request.headers.get("Idempotency-Key") or "").strip()
        if request.method != "POST" or not key:
            return view(request, *args, **kwargs)
        return _idempotent_post(request, user, key, view, args, kwargs)

    return wrapper


def _request_hash(request):
    return hashlib.sha256(
        request.method.encode("utf-8") + b"\n" + request.path.encode("utf-8") + b"\n" + (request.body or b"")
    ).hexdigest()


def _replay(row):
    response = HttpResponse(row.response_body, content_type="application/json", status=row.status_code)
    response["Idempotency-Replayed"] = "true"
    return response


def _idempotent_post(request, user, key, view, args, kwargs):
    """Run a POST once per key.

    The job (or protocol) and the stored response commit in one transaction.
    A crash rolls both back. The claim left behind is status 0; the same body
    can take it over after IDEMPOTENCY_STALE. A live claim is left alone, so a
    slow request is not run a second time.
    """
    if len(key) > 200:
        return error("Idempotency-Key is too long (max 200 characters).", 400)
    digest = _request_hash(request)
    claim = secrets.token_hex(16)
    try:
        with transaction.atomic():
            row, created = ApiIdempotency.objects.get_or_create(
                user=user,
                key=key,
                defaults={"request_hash": digest, "status_code": 0, "response_body": claim},
            )
            if not created:
                if not hmac.compare_digest(row.request_hash, digest):
                    return error("Idempotency-Key was already used with a different request.", 409)
                if row.status_code:
                    return _replay(row)
                if row.created >= timezone.now() - IDEMPOTENCY_STALE:
                    return error("A request with this Idempotency-Key is already in progress.", 409)
                took = ApiIdempotency.objects.filter(
                    pk=row.pk,
                    status_code=0,
                    request_hash=digest,
                    response_body=row.response_body,
                ).update(response_body=claim, created=timezone.now())
                if not took:
                    return error("A request with this Idempotency-Key is already in progress.", 409)
    except IntegrityError:
        return error("A request with this Idempotency-Key is already in progress.", 409)

    try:
        with transaction.atomic():
            response = view(request, *args, **kwargs)
            storable = not getattr(response, "streaming", False)
            body = response.content.decode("utf-8") if storable else ""
            if storable and len(body) > MAX_IDEMPOTENCY_BODY:
                storable = False
            if storable:
                saved = ApiIdempotency.objects.filter(pk=row.pk, status_code=0, response_body=claim).update(
                    status_code=response.status_code,
                    response_body=body,
                )
                if not saved:
                    transaction.set_rollback(True)
                    return error("A request with this Idempotency-Key is already in progress.", 409)
    except Exception:
        ApiIdempotency.objects.filter(pk=row.pk, status_code=0, response_body=claim).delete()
        raise
    if not storable:
        ApiIdempotency.objects.filter(pk=row.pk, status_code=0, response_body=claim).delete()
    return response


def read_json(request):
    raw = request.body or b""
    if not raw.strip():
        raise AgentInputError("JSON body is required.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentInputError("Request body is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise AgentInputError("JSON body must be an object.")
    return data


def _reject_unknown(payload, allowed):
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise AgentInputError("Unknown fields: {}.".format(", ".join(unknown)))


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y")
    raise AgentInputError("is_gpu_job must be a boolean.")


def _lookup(user, value, queryset, label):
    """Resolve an id or a unique name. Empty means unset."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, (list, dict)):
        raise AgentInputError("{} must be an id or a name.".format(label))
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        row = queryset.filter(pk=int(value)).first()
        if row is None:
            raise AgentInputError("{} {} was not found or is not accessible.".format(label, value))
        return row
    if isinstance(value, str):
        name = value.strip()
        if not name:
            return None
        matches = list(queryset.filter(name=name)[:2])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AgentInputError(
                "More than one {} is named '{}'. Pass the id.".format(label.lower(), name)
            )
        raise AgentInputError("{} '{}' was not found or is not accessible.".format(label, name))
    raise AgentInputError("{} must be an id or a name.".format(label))


def status_label(value):
    try:
        return str(JobStatus(value).label)
    except (ValueError, TypeError):
        return str(value)


def job_payload(job):
    protocol = job.protocol if job.protocol_id else None
    workspace = job.workspace if job.workspace_id else None
    runner = job.slave if job.slave_id else None
    return {
        "id": job.id,
        "job_name": job.job_name or "",
        "protocol": job.protocol_id,
        "protocol_name": protocol.name if protocol is not None else "",
        "protocol_ver": job.protocol_ver or "",
        "parameter": job.parameter or "",
        "input_file": job.input_file or "",
        "sample_sheet": job.sample_sheet or "",
        "comments": job.comments or "",
        "status": job.status,
        "status_label": status_label(job.status),
        "workspace": job.workspace_id,
        "workspace_name": workspace.name if workspace is not None else "",
        "runner": job.slave_id,
        "runner_name": runner.name if runner is not None else "",
        "is_gpu_job": bool(job.is_gpu_job),
        "locked": bool(job.locked),
        "visibility": job.visibility,
        "resume": job.resume,
        "result": job.result or "",
        "parent_job": job.parent_job_id,
        "create_time": job.create_time.isoformat() if job.create_time else None,
        "update_time": job.update_time.isoformat() if job.update_time else None,
    }


def list_jobs(user, params):
    page, paginator = services.paginate(services.search_jobs(user, params), None, params=params)
    return {
        "jobs": [job_payload(job) for job in page.object_list],
        "page": page.number,
        "page_size": paginator.per_page,
        "total": paginator.count,
        "has_next": page.has_next(),
    }


def resolve_protocol(user, value):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, (list, dict)):
        raise AgentInputError("protocol must be an id or a name.")
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        protocol = services.get_usable_protocol(user, int(value))
        if protocol is None:
            raise AgentInputError("Protocol {} was not found or is not accessible.".format(value))
        return protocol
    return _lookup(user, value, services.visible_protocols(user), "Protocol")


def create_job_from_payload(user, payload):
    _reject_unknown(payload, JOB_FIELDS)
    name = payload.get("job_name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise AgentInputError("job_name is required.")
    if len(name) > 100:
        raise AgentInputError("job_name is too long (max 100 characters).")
    protocol = resolve_protocol(user, payload.get("protocol"))
    if protocol is None:
        raise AgentInputError("protocol is required.")
    workspace = _lookup(user, payload.get("workspace"), services.assignable_workspaces(user), "Workspace")
    runner = _lookup(user, payload.get("runner"), services.assignable_runners(user), "Runner")
    parameter = payload.get("parameter") or ""
    input_file = payload.get("input_file") or ""
    comments = payload.get("comments") or ""
    sample_sheet = payload.get("sample_sheet") or ""
    if not isinstance(parameter, str) or not isinstance(input_file, str) or not isinstance(comments, str):
        raise AgentInputError("parameter, input_file, and comments must be strings.")
    if not isinstance(sample_sheet, str):
        raise AgentInputError("sample_sheet must be a string.")
    if (sample_sheet or "").strip() and not (getattr(protocol, "template", None) or "").strip():
        raise AgentInputError("sample_sheet applies to a protocol template. This protocol has no template.")
    array_setting = payload.get("array_setting")
    if array_setting in (None, ""):
        array_setting = None
    elif not isinstance(array_setting, str):
        raise AgentInputError("array_setting must be a string.")
    elif len(array_setting) > 100:
        raise AgentInputError("array_setting is too long (max 100 characters).")
    is_gpu = _as_bool(payload.get("is_gpu_job")) if "is_gpu_job" in payload else False
    try:
        sample_sheet = services.prepare_sample_sheet(protocol, input_file, sample_sheet)
    except services.ProtocolTemplateError:
        raise
    return services.create_job(
        delegate_for(user),
        job_name=name,
        protocol=protocol,
        parameter=parameter,
        input_file=input_file,
        workspace=workspace,
        comments=comments,
        is_gpu_job=1 if is_gpu else 0,
        array_setting=array_setting,
        sample_sheet=sample_sheet,
        slave=runner,
    )


def create_batch_from_request(user, request):
    ctype = (request.content_type or "").lower()
    raw = request.body or b""
    workspace_value = None
    if "json" in ctype or raw.lstrip().startswith(b"{") or raw.lstrip().startswith(b"["):
        payload = read_json(request)
        _reject_unknown(payload, BATCH_FIELDS)
        tsv = payload.get("tsv") or ""
        if not isinstance(tsv, str):
            raise AgentInputError("tsv must be a string.")
        workspace_value = payload.get("workspace")
    else:
        try:
            tsv = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AgentInputError("TSV body must be UTF-8.") from exc
    if not tsv.strip():
        raise AgentInputError("No TSV provided.")
    workspace = _lookup(user, workspace_value, services.assignable_workspaces(user), "Workspace")
    result = services.create_jobs_batch(delegate_for(user), tsv, workspace=workspace)
    return {
        "created": result["created"],
        "errors": result["errors"],
        "jobs": [job_payload(job) for job in result["jobs"]],
    }


def _log_payload(label, text="", truncated=False, unavailable=""):
    payload = {"kind": label, "text": text, "truncated": truncated}
    if unavailable:
        payload["unavailable"] = unavailable
    return payload


def read_job_log(job, kind):
    """Chronological stdout or stderr. A long file returns its tail."""
    kind = (kind or "stdout").lower()
    if kind in ("stdout", "out"):
        label = "stdout"
        suffix = ".log"
    elif kind in ("stderr", "err"):
        label = "stderr"
        suffix = ".err"
    else:
        raise AgentInputError("kind must be stdout or stderr.")
    try:
        from worker.bases import get_config

        log_dir = get_config("env", "log")
        if not log_dir:
            return _log_payload(label, unavailable="log directory is not configured")
        log_path = os.path.join(log_dir, "{}{}".format(job.id, suffix))
        if not os.path.isfile(log_path):
            return _log_payload(label, unavailable="log file not found")
        with open(log_path, "rb") as handle:
            size = os.path.getsize(log_path)
            if size > MAX_LOG_CHARS:
                handle.seek(max(0, size - MAX_LOG_CHARS))
                raw = handle.read(MAX_LOG_CHARS)
                truncated = True
                newline = raw.find(b"\n")
                if newline != -1 and newline + 1 < len(raw):
                    raw = raw[newline + 1 :]
            else:
                raw = handle.read()
                truncated = False
        if b"\x00" in raw[:8192]:
            return _log_payload(label, unavailable="log is not plain text")
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return _log_payload(label, unavailable="log could not be read")
    return _log_payload(label, text=text, truncated=truncated)


def contained_result_dir(job):
    """Job result folder, or None when it is not strictly inside the user directory.

    ``os.path.join`` discards the directory on its left when the right side is
    absolute, so an absolute ``job.result`` or a ``..`` segment must be rejected
    before the join. The resolved folder also has to stay under the user root
    after symlinks are followed.
    """
    run_dir = (job.run_dir or "").strip()
    result = (job.result or "").strip().replace("\\", "/")
    if not run_dir or not result or result.startswith("/") or os.path.isabs(result):
        return None
    if any(part in ("", ".", "..") for part in result.split("/")):
        return None
    root = os.path.realpath(os.path.join(run_dir, str(job.user_id)))
    folder = os.path.realpath(os.path.join(root, result))
    if not folder.startswith(root + os.sep):
        return None
    return folder


def _empty_file_page(params):
    return {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
        "has_more": False,
        "q": params.get("q") or "",
        "sort": "name",
        "order": "asc",
        "next_offset": 0,
    }


def list_result_files(job, params):
    if contained_result_dir(job) is None:
        return _empty_file_page(params)
    page = page_job_files(
        job,
        q=params.get("q") or "",
        sort=params.get("sort") or "name",
        order=params.get("order") or "asc",
        limit=params.get("limit") or 50,
        offset=params.get("offset") or 0,
    )
    page["items"] = [
        {
            "name": item.get("name") or "",
            "size": item.get("file_size") or 0,
            "size_label": item.get("size_label") or "",
            "created": item.get("file_create") or "",
            "is_link": bool(item.get("is_link")),
        }
        for item in page["items"]
    ]
    return page


def open_named_result(job, name):
    """Open one file inside the job result folder. Paths that leave it fail."""
    root = contained_result_dir(job)
    raw = (name or "").strip().replace("\\", "/")
    if root is None or not raw or raw.startswith("/") or any(part == ".." for part in raw.split("/")):
        return None
    full = os.path.realpath(os.path.join(root, raw))
    if not full.startswith(root + os.sep):
        return None
    if not os.path.isfile(full):
        return None
    return full


def download_named_result(job, name):
    path = open_named_result(job, name)
    if path is None:
        return None
    return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))


def job_graph(user, job_id, params):
    graph = services.build_job_dag(
        user,
        job_id,
        up=params.get("up", 1),
        down=params.get("down", 1),
        max_nodes=params.get("max_nodes", 300),
    )
    if graph is None:
        return None
    for node in graph["nodes"]:
        node["status_label"] = status_label(node.get("status"))
    return graph


def list_protocols(user):
    queryset = services.visible_protocols(user)
    total = queryset.count()
    rows = []
    for protocol in queryset[:PROTOCOL_LIST_LIMIT]:
        rows.append(
            {
                "id": protocol.id,
                "name": protocol.name,
                "description": protocol.description or "",
                "ver": protocol.ver or "",
                "template": bool((protocol.template or "").strip()),
            }
        )
    return {"protocols": rows, "total": total, "has_more": total > len(rows)}


def protocol_document(user, pk):
    protocol = services.get_visible_protocol(user, pk)
    if protocol is None:
        return None
    return services.protocol_json_payload(protocol, user)


def import_protocol_document(user, payload):
    document = payload
    if "step" not in payload and "pipeline" not in payload and isinstance(payload.get("protocol"), dict):
        document = payload["protocol"]
    protocol, missing, env_notes = services.import_protocol_from_json(user, document)
    return {
        "protocol": {
            "id": protocol.id,
            "name": protocol.name,
            "description": protocol.description or "",
            "ver": protocol.ver or "",
        },
        "missing_references": missing,
        "unchanged_environments": env_notes,
    }


def list_workspaces(user):
    return {
        "workspaces": [
            {"id": row.id, "name": row.name}
            for row in services.assignable_workspaces(user)
        ]
    }


def list_runners(user):
    return {
        "runners": [
            {"id": row.id, "name": row.name}
            for row in services.assignable_runners(user)
        ]
    }


def discovery():
    return {
        "name": "BioQueue agent API",
        "version": 1,
        "auth": "Authorization: Bearer <api_key>",
        "token": "The api_key is on the Account page. Rotating it revokes the old key.",
        "idempotency": (
            "Optional Idempotency-Key header on POST. The same key and body replay "
            "the first response. A different body with the same key returns 409."
        ),
        "errors": "Failures are {\"error\": \"...\"} with an HTTP 4xx status.",
        "endpoints": [
            {"method": "GET", "path": "/api/v1/", "description": "This document."},
            {
                "method": "GET",
                "path": "/api/v1/jobs/",
                "description": "List jobs. Query keys match the job monitor: q, status, protocol, workspace, job_name, scope, page, page_size.",
            },
            {
                "method": "POST",
                "path": "/api/v1/jobs/",
                "description": "Create one job. protocol, workspace, and runner accept an id or a unique name.",
            },
            {
                "method": "POST",
                "path": "/api/v1/jobs/batch/",
                "description": "Create jobs from TSV columns protocol_id, job_name, input_file, parameter, optional array_setting, optional is_gpu. 201 when every row is created, 207 when some rows are skipped, 400 when none are.",
            },
            {"method": "GET", "path": "/api/v1/jobs/<id>/", "description": "Job status, parameters, and inputs."},
            {
                "method": "GET",
                "path": "/api/v1/jobs/<id>/logs/?kind=stdout|stderr",
                "description": "Chronological stdout or stderr. A long log returns the tail and truncated is true.",
            },
            {"method": "GET", "path": "/api/v1/jobs/<id>/files/", "description": "Files in the job result folder."},
            {
                "method": "GET",
                "path": "/api/v1/jobs/<id>/files/download/?name=",
                "description": "Download one result file by its relative name.",
            },
            {
                "method": "GET",
                "path": "/api/v1/jobs/<id>/dag/?up=&down=&max_nodes=",
                "description": "Jobs this run depends on and jobs built from it.",
            },
            {"method": "GET", "path": "/api/v1/protocols/", "description": "Protocols this account can run. has_more is true when the list is capped."},
            {"method": "GET", "path": "/api/v1/protocols/<id>/", "description": "Protocol JSON."},
            {"method": "POST", "path": "/api/v1/protocols/import/", "description": "Import a protocol JSON document."},
            {"method": "GET", "path": "/api/v1/workspaces/", "description": "Workspaces this account can assign."},
            {"method": "GET", "path": "/api/v1/runners/", "description": "Named runners. SSH details are not included."},
        ],
    }
