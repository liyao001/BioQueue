from functools import wraps
from urllib.parse import quote

from django.http import HttpResponse
from django.shortcuts import redirect

from .http import is_htmx

LOGIN_URL = "/ui/login/"


def ui3_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            nxt = request.get_full_path()
            login_to = "{}?next={}".format(LOGIN_URL, quote(nxt, safe="/"))
            if is_htmx(request):
                response = HttpResponse(status=401)
                response["HX-Redirect"] = login_to
                return response
            return redirect(login_to)
        return view(request, *args, **kwargs)

    return wrapper
