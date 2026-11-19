import os

from django.http import FileResponse, Http404, HttpResponseForbidden
from django.views.decorators.http import require_GET, require_http_methods

from .. import services
from ..decorators import ui3_login_required
from ..http import list_params, querystring, render_htmx
from ..job_archive import present_archive, resolve_archive_download


@ui3_login_required
@require_http_methods(["GET"])
def archive_list(request):
    params = list_params(request)
    archives = services.visible_archives(request.user)
    page, paginator = services.paginate(archives, request, params=params)
    items = list(page.object_list)
    for archive in items:
        archive.ui3_status = services.archive_status_label(archive.status)
        present_archive(archive)
    return render_htmx(
        request,
        "ui3/archives/list.html",
        "ui3/archives/_table.html",
        {
            "page_obj": page,
            "paginator": paginator,
            "archives": items,
            "filters": params,
            "qs": querystring(request),
            "page_size": page.paginator.per_page,
            "page_size_choices": (12, 24, 36, 48),
            "item_label": "archive",
        },
    )


@ui3_login_required
@require_GET
def archive_download(request, pk):
    archive = services.get_visible_archive(request.user, pk)
    if archive is None:
        return HttpResponseForbidden("You cannot download this archive.")
    path = resolve_archive_download(archive)
    if path is None:
        raise Http404("Archive file is not available.")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))
