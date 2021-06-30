from django.shortcuts import render
from .forms import LoginForm, PasswordChangeForm, UserRegisterForm
from django.contrib.auth import authenticate, login, update_session_auth_hash
from ui.tools import success, error
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group


def user_login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = authenticate(username=cd['username'], password=cd['password'])

            if user is not None:
                if user.is_active:
                    login(request, user)
                    if "next" in request.POST.keys():
                        red_url = request.POST["next"]
                        if red_url == "":
                            red_url = "/ui"
                    else:
                        red_url = "/ui"
                    return success('Authenticated successfully', red_url)
                else:
                    return error('Disabled account')
            else:
                return error('Wrong username or password')
        else:
            return error(str(form.errors))
    else:
        form = LoginForm()
    if "next" in request.GET.keys():
       return render(request, 'accounts/login.html', {'form': form, 'next': request.GET["next"]})
    else:
        return render(request, 'accounts/login.html', {'form': form})


def register(request):
    if request.method == 'POST':
        user_form = UserRegisterForm(request.POST)
        if user_form.is_valid():
            new_user = user_form.save(commit=False)
            new_user.set_password(
                user_form.cleaned_data['password']
            )
            new_user.is_active = False
            new_user.save()
            try:
                group = Group.objects.get(name="normal")
                new_user.groups.add(group)
            except Exception as e:
                return error(e)
            return success('Your account has been successfully created.', '/accounts/login')
        else:
            return error(str(user_form.errors))
    else:
        user_form = UserRegisterForm()
    return render(request, 'accounts/register.html', {'form': user_form})


@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.POST)
        if form.is_valid():
            username = request.user.username
            cd = form.cleaned_data
            user = authenticate(username=username, password=cd['old_password'])
            if user is not None and user.is_active:
                new_password = cd['new_password_1']
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, username)
                return success('Your password had been updated.', 'accounts:login')
            else:
                return error('Password doesn\'t match.')
        else:
            return error('Your form is illegal.')
    else:
        return error('Please confirm your approaching method.')
