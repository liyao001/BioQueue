from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from ..decorators import LOGIN_URL, ui3_login_required
from ..files import clean_unlinked_job_folders
from ..http import htmx_error, hx_redirect, is_htmx
from .. import services


def _next_inside_ui3(request):
    nxt = request.POST.get("next") or request.GET.get("next") or "/ui3/jobs/"
    if not nxt.startswith("/ui3/"):
        nxt = "/ui3/jobs/"
    return nxt


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("ui3:jobs")
    error = None
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is not None and getattr(user, "is_active", False):
            login(request, user)
            nxt = _next_inside_ui3(request)
            if is_htmx(request):
                from django.http import HttpResponse

                response = HttpResponse(status=204)
                response["HX-Redirect"] = nxt
                return response
            return redirect(nxt)
        error = "Invalid username or password."
    return render(
        request,
        "ui3/login.html",
        {"error": error, "next": request.GET.get("next") or request.POST.get("next") or ""},
    )


@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return redirect(LOGIN_URL)


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect("ui3:jobs")
    error = None
    form = {
        "username": (request.POST.get("username") or "").strip() if request.method == "POST" else "",
        "email": (request.POST.get("email") or "").strip() if request.method == "POST" else "",
        "first_name": (request.POST.get("first_name") or "").strip() if request.method == "POST" else "",
        "last_name": (request.POST.get("last_name") or "").strip() if request.method == "POST" else "",
    }
    if request.method == "POST":
        username = form["username"]
        password = request.POST.get("password") or ""
        password_2 = request.POST.get("password_2") or ""
        if not username:
            error = "Username is required."
        elif len(username) > 150:
            error = "Username is too long (max 150 characters)."
        elif User.objects.filter(username=username).exists():
            error = "That username is already taken."
        elif not password:
            error = "Password is required."
        elif password != password_2:
            error = "Passwords do not match."
        elif form["email"] and len(form["email"]) > 254:
            error = "Email is too long (max 254 characters)."
        elif len(form["first_name"]) > 150 or len(form["last_name"]) > 150:
            error = "Name is too long (max 150 characters)."
        else:
            user = User(
                username=username,
                email=form["email"],
                first_name=form["first_name"],
                last_name=form["last_name"],
                is_active=False,
            )
            try:
                user.full_clean(exclude=["password"])
            except ValidationError as exc:
                error = "; ".join(msg for msgs in exc.message_dict.values() for msg in msgs)
            if error is None:
                try:
                    validate_password(password, user)
                except ValidationError as exc:
                    error = "; ".join(exc.messages)
            if error is None:
                user.set_password(password)
                user.save()
                group, _created = Group.objects.get_or_create(name="normal")
                user.groups.add(group)
                messages.success(request, "Account created. An administrator must activate it before you can sign in.")
                return redirect("ui3:login")
    return render(request, "ui3/register.html", {"error": error, "form": form})


def _account_context(request, *, password_error=None, folder_error=None):
    profile = services.profile_for(request.user)
    folders = services.folder_defaults_for(request.user)
    return {
        "profile": profile,
        "folders": folders,
        "password_error": password_error,
        "folder_error": folder_error,
        "upload_folder": folders.get("upload_folder") or "",
        "archive_folder": folders.get("archive_folder") or "",
    }


@ui3_login_required
@require_http_methods(["GET", "POST"])
def account_view(request):
    password_error = None
    folder_error = None
    if request.method == "POST":
        section = (request.POST.get("section") or "").strip()
        if section == "password":
            old_password = request.POST.get("old_password") or ""
            new_password = request.POST.get("new_password") or ""
            confirm = request.POST.get("new_password_2") or ""
            if not request.user.check_password(old_password):
                password_error = "Current password is incorrect."
            elif not new_password:
                password_error = "New password is required."
            elif new_password != confirm:
                password_error = "New passwords do not match."
            else:
                try:
                    validate_password(new_password, request.user)
                except ValidationError as exc:
                    password_error = "; ".join(exc.messages)
            if password_error:
                if is_htmx(request):
                    return htmx_error(password_error)
            else:
                request.user.set_password(new_password)
                request.user.save(update_fields=["password"])
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password updated.")
                if is_htmx(request):
                    return hx_redirect(reverse("ui3:account"))
                return redirect("ui3:account")
        elif section == "folders":
            upload_folder = (request.POST.get("upload_folder") or "").strip()
            archive_folder = (request.POST.get("archive_folder") or "").strip()
            if len(upload_folder) > 1024 or len(archive_folder) > 1024:
                folder_error = "Folder path is too long (max 1024 characters)."
                if is_htmx(request):
                    return htmx_error(folder_error)
            else:
                profile = services.profile_for(request.user)
                if profile is None:
                    folder_error = "No profile found for this account."
                    if is_htmx(request):
                        return htmx_error(folder_error)
                else:
                    profile.upload_folder = upload_folder
                    profile.archive_folder = archive_folder
                    profile.save(update_fields=["upload_folder", "archive_folder"])
                    messages.success(request, "Folder paths updated.")
                    if is_htmx(request):
                        return hx_redirect(reverse("ui3:account"))
                    return redirect("ui3:account")
        else:
            if is_htmx(request):
                return htmx_error("Unknown account form.")
            messages.error(request, "Unknown account form.")
            return redirect("ui3:account")
    return render(
        request,
        "ui3/account.html",
        _account_context(request, password_error=password_error, folder_error=folder_error),
    )


@ui3_login_required
@require_POST
def clean_folders_view(request):
    result = clean_unlinked_job_folders(request.user)
    if result is None:
        message = "Workspace path is not configured; refusing to clean folders."
        if is_htmx(request):
            return htmx_error(message)
        messages.error(request, message)
        return redirect("ui3:account")
    detected, live, failed = result
    message = "{} unlinked folder(s) found among {} live job folder(s). {} failed to remove.".format(
        detected, live, failed
    )
    messages.success(request, message)
    if is_htmx(request):
        return hx_redirect(reverse("ui3:account"))
    return redirect("ui3:account")
