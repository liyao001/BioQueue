from django import forms
from django.contrib.auth.models import User


class LoginForm(forms.Form):
    username = forms.CharField(
        required=True,
        label=False,
        error_messages={"required": "Please type username"},
        widget=forms.TextInput(
            attrs={
                "placeholder": "Username / Project name",
                "class": "form-control",
            }
        ),
    )
    password = forms.CharField(
        required=True,
        label=False,
        error_messages={"required": "Please type your password"},
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Password",
                "class": "form-control",
            }
        )
    )


class PasswordChangeForm(forms.Form):
    old_password = forms.CharField(
        required=True,
        label="Raw Password",
        error_messages={"required": "Please type your raw password"},
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Raw password",
            }
        )
    )
    new_password_1 = forms.CharField(
        required=True,
        label="New Password",
        error_messages={"required": "Please type your new password"},
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "New password",
            }
        )
    )
    new_password_2 = forms.CharField(
        required=True,
        label="Confirm Password",
        error_messages={"required": "Please confirm new password"},
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm new password",
            }
        )
    )


class UserRegisterForm(forms.ModelForm):
    password = forms.CharField(
        required=True,
        label=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Password",
            }
        )
    )
    password_2 = forms.CharField(
        required=True,
        label=False,
        widget=forms.PasswordInput(
            attrs={
                "class": 'form-control',
                "placeholder": "Confirm password",
            }
        )
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "Username / Project name"}),
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Last name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "E-mail"}),
        }
        labels = {
            "username": False,
            "first_name": False,
            "last_name": False,
            "email": False,
        }
        help_texts = {
            "username": False,
            "first_name": False,
            "last_name": False,
        }

    def clean_password2(self):
        cd = self.cleaned_data
        if cd["password"] != cd["password_2"]:
            raise forms.ValidationError('Password doesn\'t match.')
        return cd["password_2"]
