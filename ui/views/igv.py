import os
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from ..decorators import ui3_login_required
from ..genome import GENOMES, describe_igv_file, genomic_files
from ..http import delegate_for, int_or_none
from .. import services


def _bytes_url(job_id, trace):
    return "{}?{}".format(
        reverse("ui3:job_file_bytes", args=[job_id]),
        urlencode({"trace": trace}),
    )


def _track_payload(job, trace):
    info = describe_igv_file(job, trace)
    if info is None:
        return None
    info["job"] = job.id
    info["job_name"] = job.job_name or ""
    info["trace"] = trace
    base = os.path.basename(info.get("name") or "")
    info["label"] = "#{} {}".format(job.id, base or info.get("name") or "track")
    if not info.get("ok"):
        info.pop("index_trace", None)
        info.pop("gzi_trace", None)
        return info
    index_trace = info.pop("index_trace", None)
    gzi_trace = info.pop("gzi_trace", None)
    info["url"] = _bytes_url(job.id, trace)
    info["indexURL"] = _bytes_url(job.id, index_trace) if index_trace else None
    info["compressedIndexURL"] = _bytes_url(job.id, gzi_trace) if gzi_trace else None
    return info


IGV_JOB_PAGE = 15


def recent_igv_jobs(user, q="", page=1):
    """One page of readable top-level jobs for the track picker."""
    delegate = delegate_for(user)
    qs = services.owned_jobs(user, scope="all").filter(parent_job__isnull=True)
    text = (q or "").strip()
    if text.isdigit():
        qs = qs.filter(Q(pk=int(text)) | Q(job_name__icontains=text))
    elif text:
        qs = qs.filter(job_name__icontains=text)
    owner_id = getattr(delegate, "id", None)
    try:
        page_number = int(page)
    except (TypeError, ValueError):
        page_number = 1
    job_page = Paginator(qs.order_by("-pk"), IGV_JOB_PAGE).get_page(page_number)
    rows = [
        {
            "id": job.id,
            "job_name": job.job_name,
            "shared": job.user_id != owner_id,
        }
        for job in job_page.object_list
    ]
    return rows, job_page


@ui3_login_required
@require_GET
def igv_page(request):
    jobs, job_page = recent_igv_jobs(request.user)
    return render(
        request,
        "ui3/igv/page.html",
        {
            "genomes": GENOMES,
            "jobs": jobs,
            "job_page": job_page,
            "q": "",
        },
    )


@ui3_login_required
@require_GET
def igv_track(request):
    job_id = int_or_none(request.GET.get("job"))
    trace = request.GET.get("trace") or ""
    if job_id is None or not trace:
        return JsonResponse({"ok": False, "detail": "job and trace are required."}, status=400)
    job = services.get_readable_job(request.user, job_id)
    if job is None:
        return JsonResponse({"ok": False, "detail": "Job not found or not accessible."}, status=404)
    payload = _track_payload(job, trace)
    if payload is None:
        return JsonResponse({"ok": False, "detail": "File not found."}, status=404)
    return JsonResponse(payload)


@ui3_login_required
@require_GET
def igv_jobs(request):
    q = request.GET.get("q") or ""
    jobs, job_page = recent_igv_jobs(request.user, q, request.GET.get("page") or 1)
    return render(
        request,
        "ui3/igv/_jobs.html",
        {"jobs": jobs, "job_page": job_page, "q": q},
    )


@ui3_login_required
@require_GET
def igv_files(request):
    job_id = int_or_none(request.GET.get("job"))
    job = services.get_readable_job(request.user, job_id) if job_id is not None else None
    q = request.GET.get("fq") or request.GET.get("q") or ""
    if job is None:
        return render(
            request,
            "ui3/igv/_files.html",
            {"job": None, "items": [], "truncated": False, "error": "Job not found or not accessible."},
        )
    items, truncated = genomic_files(job, q=q)
    return render(
        request,
        "ui3/igv/_files.html",
        {"job": job, "items": items, "truncated": truncated, "error": ""},
    )
