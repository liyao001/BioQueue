from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..decorators import ui3_login_required
from ..http import csv_ints, int_or_none
from .. import services


@ui3_login_required
@require_GET
def dag_page(request):
    return render(request, "ui3/dag/explorer.html")


@ui3_login_required
@require_GET
def dag_graph(request):
    root_id = int_or_none(request.GET.get("root"))
    if root_id is None:
        return JsonResponse({"detail": "root is required and must be an integer"}, status=400)
    data = services.build_job_dag(
        request.user,
        root_id,
        up=request.GET.get("up", 1),
        down=request.GET.get("down", 1),
        max_nodes=request.GET.get("max_nodes", 300),
    )
    if data is None:
        return JsonResponse({"detail": "root job not found"}, status=404)
    return JsonResponse(data)


@ui3_login_required
@require_GET
def dag_search(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})
    params = {"q": q, "scope": "all", "page_size": "10"}
    jobs = list(services.search_jobs(request.user, params)[:10])
    return JsonResponse({
        "results": [{"id": j.id, "job_name": j.job_name, "status": j.status} for j in jobs],
    })


@ui3_login_required
@require_GET
def dag_jobs(request):
    ids = csv_ints(request.GET.get("ids") or request.GET.get("q") or "")
    return JsonResponse({"results": services.job_seed_summaries(request.user, ids)})
