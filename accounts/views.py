from django.shortcuts import render
from .forms import LoginForm, PasswordChangeForm, UserRegisterForm
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.http import HttpResponse
from ui.tools import success, error
from django.contrib.auth.decorators import login_required


def user_login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = authenticate(username=cd['username'], password=cd['password'])

            if user is not None:
                if user.is_active:
                    login(request, user)
                    return success('Authenticated successfully', '/ui')
                else:
                    return error('Disabled account')
            else:
                return error('Wrong username or password')
        else:
            return error(str(form.errors))
    else:
        form = LoginForm()
    return render(request, 'accounts/login.html', {'form': form})


def register(request):
    if request.method == 'POST':
        user_form = UserRegisterForm(request.POST)
        if user_form.is_valid():
            new_user = user_form.save(commit=False)
            new_user.set_password(
                user_form.cleaned_data['password']
            )
            new_user.save()
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
                return error('Password don\'t match.')
        else:
            return error('Your form is illegal.')
    else:
        return error('Please confirm your approaching method.')
