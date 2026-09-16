from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from ..decorators import ui3_login_required
from ..http import list_params, querystring, render_htmx
from .. import services


@ui3_login_required
@require_http_methods(["GET"])
def archive_list(request):
    params = list_params(request)
    archives = services.visible_archives(request.user)
    page, paginator = services.paginate(archives, request, params=params)
    items = list(page.object_list)
    for archive in items:
        archive.ui3_status = services.archive_status_label(archive.status)
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
