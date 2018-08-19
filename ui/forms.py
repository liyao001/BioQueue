from django import forms
from django.template.defaultfilters import filesizeformat
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError


class SingleJobForm(forms.Form):
    protocol = forms.IntegerField(
        required=True,
        widget=forms.Select(
            attrs={
                'class': u'input-block-level',
            }
        )
    )

    input_files = forms.CharField(
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

    job_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )


class FetchRemoteProtocolForm(forms.Form):
    uid = forms.CharField(
        required=True,
        max_length=36,
    )


class JobManipulateForm(forms.Form):
    job = forms.IntegerField(
        required=True
    )
    step = forms.IntegerField(
        required=False
    )


class ProtocolManipulateForm(forms.Form):
    parent = forms.IntegerField(
        required=True
    )


class RefManipulateForm(forms.Form):
    id = forms.IntegerField(
        required=True,
    )
    path = forms.CharField(
        required=True,
        max_length=500,
    )


class CreateProtocolForm(forms.Form):
    name = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )


class CreateStepForm(forms.Form):
    software = forms.CharField(
        required=False,
        max_length=50,
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
    insert_to = forms.IntegerField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )
    force_local = forms.IntegerField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )


class StepManipulateForm(forms.Form):
    """
    parent = forms.IntegerField(
        required=True,
    )
    """
    id = forms.IntegerField(
        required=True,
    )
    parameter = forms.CharField(
        required=False,
    )


class StepOrderManipulateForm(forms.Form):
    protocol = forms.IntegerField(
        required=True,
    )
    step_order = forms.CharField(
        required=True,
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
        max_length=255,
    )
    path = forms.CharField(
        required=True,
        max_length=500,
    )
    description = forms.CharField(
        required=False,
    )
    source = forms.CharField(
        required=False,
    )


class CommentManipulateForm(forms.Form):
    trace = forms.IntegerField(
        required=True,
    )
    content = forms.CharField(
        required=True,
        max_length=500,
    )


class RestrictedFileField(forms.FileField):

    def __init__(self, *args, **kwargs):
        self.content_types = kwargs.pop("content_types")
        self.max_upload_size = kwargs.pop("max_upload_size")

        super(RestrictedFileField, self).__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        file = super(RestrictedFileField, self).clean(data, initial)

        try:
            content_type = file.content_type
            if content_type in self.content_types:
                if file._size > self.max_upload_size:
                    raise ValidationError(_('Please keep filesize under %s. Current filesize %s') % (
                        filesizeformat(self.max_upload_size), filesizeformat(file._size)))
            else:
                raise ValidationError(_('Filetype not supported.'))
        except AttributeError:
            pass

        return data


class BatchJobForm(forms.Form):
    job_list = RestrictedFileField(content_types=['text/plain'], max_upload_size=2621440)
