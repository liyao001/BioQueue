from django import forms
from django.contrib.auth.models import User


class LoginForm(forms.Form):
    username = forms.CharField(
        required=True,
        label=u'Username',
        error_messages={'required': 'Please type username'},
        widget=forms.TextInput(
            attrs={
                'placeholder': u'Username',
                'class': u'input-block-level',
            }
        )
    )
    password = forms.CharField(
        required=True,
        label=u'Password',
        error_messages={'required': 'Please type your password'},
        widget=forms.PasswordInput(
            attrs={
                'placeholder': u'Password',
                'class': u'input-block-level',
            }
        )
    )


class PasswordChangeForm(forms.Form):
    old_password = forms.CharField(
        required=True,
        label=r'Raw Password',
        error_messages={'required': u'Please type your raw password'},
        widget=forms.PasswordInput(
            attrs={
                'placeholder': u'Raw password',
            }
        )
    )
    new_password_1 = forms.CharField(
        required=True,
        label=r'New Password',
        error_messages={'required': u'Please type your new password'},
        widget=forms.PasswordInput(
            attrs={
                'placeholder': u'New password',
            }
        )
    )
    new_password_2 = forms.CharField(
        required=True,
        label=r'Confirm Password',
        error_messages={'required': u'Please confirm new password'},
        widget=forms.PasswordInput(
            attrs={
                'placeholder': u'Confirm new password',
            }
        )
    )


class UserRegisterForm(forms.ModelForm):
    password = forms.CharField(
        required=True,
        label='Password',
        widget=forms.PasswordInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )
    password_2 = forms.CharField(
        required=True,
        label='Repeat password',
        widget=forms.PasswordInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'email')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'input-block-level'}),
            'first_name': forms.TextInput(attrs={'class': 'input-block-level'}),
            'email': forms.EmailInput(attrs={'class': 'input-block-level'}),
        }

    def clean_password2(self):
        cd = self.cleaned_data
        if cd['password'] != cd['password_2']:
            raise forms.ValidationError('Password don\'t match.')
        return cd['password_2']
