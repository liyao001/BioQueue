"""HTMX helpers for ui3 views."""

import re
from urllib.parse import urlparse

from django.http import HttpResponse, QueryDict
from django.shortcuts import render
from django.template.loader import render_to_string

ARRAY_PATH_RE = re.compile(r"/ui(?:3)?/jobs/(\d+)/array/?$")


# Filter / pagination keys preserved across HTMX POST refreshes.
LIST_FILTER_KEYS = (
    "q",
    "job_name",
    "job_name_not",
    "parameter",
    "parameter_not",
    "input_file",
    "input_file_not",
    "protocol",
    "protocol_name",
    "protocol_name_not",
    "workspace",
    "workspace_name",
    "workspace_name_not",
    "status",
    "status_not",
    "visibility",
    "id",
    "id_not",
    "parent_job",
    "parent",
    "scope",
    "mode",
    "auto",
    "page",
    "page_size",
    "select",
    "ordering",
    "state",
)


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def delegate_for(user):
    """Return the QueueDB profile delegate, falling back to the user."""
    prof = getattr(user, "queuedb_profile_related", None)
    return getattr(prof, "delegate", user)


def array_parent_from_request(request):
    """Job id from /ui/jobs/<id>/array/ on the request path or HX-Current-URL."""
    candidates = [getattr(request, "path", "") or ""]
    hx = request.headers.get("HX-Current-URL") or ""
    if hx:
        candidates.append(urlparse(hx).path)
    for path in candidates:
        match = ARRAY_PATH_RE.search(path)
        if match:
            return int(match.group(1))
    return None


def list_params(request):
    """
    Params for job list search/pagination.

    On POST (e.g. HTMX action refresh), GET is empty — recover filters from
    HX-Current-URL query string, then fall back to filter-like POST fields.
    Always merge any present GET params (GET wins on key conflict).
    """
    params = QueryDict(mutable=True)
    if request.method == "POST":
        hx_url = request.headers.get("HX-Current-URL") or ""
        if hx_url:
            qs = urlparse(hx_url).query
            if qs:
                params = QueryDict(qs, mutable=True)
        else:
            for key in LIST_FILTER_KEYS:
                if key in request.POST:
                    params.setlist(key, request.POST.getlist(key))
    if request.GET:
        for key in request.GET:
            params.setlist(key, request.GET.getlist(key))
    return params


def querystring(request, **updates):
    """Copy list params and overlay updates. Pass None to drop a key."""
    q = list_params(request).copy()
    for key, value in updates.items():
        if value is None or value == "":
            q.pop(key, None)
        else:
            q[key] = value
    return q.urlencode()


def render_htmx(request, full_template, partial_template, context, **kwargs):
    template = partial_template if is_htmx(request) else full_template
    return render(request, template, context, **kwargs)


def hx_redirect(url):
    response = HttpResponse(status=204)
    response["HX-Redirect"] = url
    return response


def hx_refresh():
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


def toast_html(message, level="success"):
    return render_to_string(
        "ui3/partials/toast.html",
        {"message": message, "level": level},
    )


def with_toast(response, message, level="success"):
    """Append an out-of-band toast to an existing HTML response."""
    extra = toast_html(message, level)
    if isinstance(response, HttpResponse):
        response.content = response.content + extra.encode("utf-8")
        return response
    return response


def htmx_error(message, status=400):
    """
    HTMX-friendly error: toast into #toast-root without wiping #job-results.
    """
    html = toast_html(message, "error")
    response = HttpResponse(html, status=status)
    response["HX-Retarget"] = "#toast-root"
    response["HX-Reswap"] = "innerHTML"
    return response


def combo_query(request):
    """Keyword for searchable combos. Prefer combo_q so job-search q is not reused."""
    return (request.GET.get("combo_q") or request.GET.get("q") or "").strip()


def int_or_none(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def csv_ints(value):
    out = []
    if not value:
        return out
    for token in str(value).replace(",", " ").split():
        try:
            out.append(int(token))
        except ValueError:
            continue
    return out


def empty_querydict():
    return QueryDict(mutable=True)


def redirect_ui3_prefix(request, rest=""):
    """Send old /ui3/… bookmarks to the same path under /ui/."""
    from django.shortcuts import redirect

    return redirect("/ui/" + (rest or ""))
