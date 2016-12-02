from django import forms
from .models import ProtocolList


class SingleJobForm(forms.Form):
    protocol = forms.IntegerField(
        required=True,
        widget=forms.Select(
            attrs={
                'class': u'input-block-level',
            }
        )
    )

    input_file_rf = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )

    input_file_r = forms.CharField(
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={
                'class': u'input-block-level',
            }
        )
    )

    parameter = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )


class JobManipulateForm(forms.Form):
    job = forms.IntegerField(
        required=True
    )


class ProtocolManipulateForm(forms.Form):
    parent = forms.IntegerField(
        required=True
    )


class CreateProtocolForm(forms.Form):
    name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )


class CreateStepForm(forms.Form):
    software = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )
    parameter = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )
    parent = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput()
    )


class StepManipulateForm(forms.Form):
    parent = forms.IntegerField(
        required=True,
    )
    id = forms.IntegerField(
        required=True,
    )
    parameter = forms.CharField(
        required=False,
    )


class ShareProtocolForm(forms.Form):
    peer = forms.CharField(
        required=True,
    )
    pro = forms.IntegerField(
        required=True,
    )


class QueryLearningForm(forms.Form):
    stephash = forms.CharField(
        required=True,
    )
    type = forms.IntegerField(
        required=True,
    )


class CreateReferenceForm(forms.Form):
    name = forms.CharField(
        required=True,
    )
    path = forms.CharField(
        required=True,
    )
