"""HTTP entry points for the agent API. Parsing and JSON live here; records go through services."""

from django.http import JsonResponse

from .. import services
from ..agent_api import (
    AgentInputError,
    agent_api,
    create_batch_from_request,
    create_job_from_payload,
    discovery,
    download_named_result,
    error,
    import_protocol_document,
    job_graph,
    job_payload,
    list_jobs,
    list_protocols,
    list_result_files,
    list_runners,
    list_workspaces,
    protocol_document,
    read_job_log,
    read_json,
)


def _method(request, allowed):
    if request.method not in allowed:
        response = error("Method not allowed.", 405)
        response["Allow"] = ", ".join(allowed)
        return response
    return None


def _readable(request, pk):
    job = services.get_readable_job(request.agent_user, pk)
    if job is None:
        return None, error("Job not found or not accessible.", 404)
    return job, None


@agent_api
def index(request):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    return JsonResponse(discovery())


@agent_api
def jobs(request):
    rejected = _method(request, ("GET", "POST"))
    if rejected:
        return rejected
    if request.method == "GET":
        return JsonResponse(list_jobs(request.agent_user, request.GET))
    try:
        job = create_job_from_payload(request.agent_user, read_json(request))
    except (AgentInputError, services.ProtocolTemplateError) as exc:
        return error(str(exc), 400)
    job = services.get_readable_job(request.agent_user, job.id) or job
    return JsonResponse({"job": job_payload(job)}, status=201)


@agent_api
def jobs_batch(request):
    rejected = _method(request, ("POST",))
    if rejected:
        return rejected
    try:
        result = create_batch_from_request(request.agent_user, request)
    except AgentInputError as exc:
        return error(str(exc), 400)
    if not result["created"]:
        result = dict(result)
        result["error"] = "No jobs were created."
        return JsonResponse(result, status=400)
    if result["errors"]:
        result = dict(result)
        result["error"] = "Some rows were skipped."
        return JsonResponse(result, status=207)
    return JsonResponse(result, status=201)


@agent_api
def job_detail(request, pk):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    job, err = _readable(request, pk)
    if err:
        return err
    return JsonResponse({"job": job_payload(job)})


@agent_api
def job_logs(request, pk):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    job, err = _readable(request, pk)
    if err:
        return err
    try:
        payload = read_job_log(job, request.GET.get("kind"))
    except AgentInputError as exc:
        return error(str(exc), 400)
    return JsonResponse(payload)


@agent_api
def job_files(request, pk):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    job, err = _readable(request, pk)
    if err:
        return err
    return JsonResponse(list_result_files(job, request.GET))


@agent_api
def job_file_download(request, pk):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    job, err = _readable(request, pk)
    if err:
        return err
    response = download_named_result(job, request.GET.get("name"))
    if response is None:
        return error("File not found.", 404)
    return response


@agent_api
def job_dag(request, pk):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    graph = job_graph(request.agent_user, pk, request.GET)
    if graph is None:
        return error("Job not found or not accessible.", 404)
    return JsonResponse(graph)


@agent_api
def protocols(request):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    return JsonResponse(list_protocols(request.agent_user))


@agent_api
def protocol_detail(request, pk):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    document = protocol_document(request.agent_user, pk)
    if document is None:
        return error("Protocol not found or not accessible.", 404)
    return JsonResponse(document)


@agent_api
def protocol_import(request):
    rejected = _method(request, ("POST",))
    if rejected:
        return rejected
    try:
        result = import_protocol_document(request.agent_user, read_json(request))
    except (AgentInputError, services.ProtocolImportError) as exc:
        return error(str(exc), 400)
    return JsonResponse(result, status=201)


@agent_api
def workspaces(request):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    return JsonResponse(list_workspaces(request.agent_user))


@agent_api
def runners(request):
    rejected = _method(request, ("GET",))
    if rejected:
        return rejected
    return JsonResponse(list_runners(request.agent_user))
