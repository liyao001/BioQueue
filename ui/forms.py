#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Li Yao
# @Date: 12/01/16
from django import forms
from django.template.defaultfilters import filesizeformat
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError
from django.forms import TextInput, Select, Textarea
from django.core.validators import RegexValidator
from QueueDB.models import Workspace, VirtualEnvironment, Experiment, Step, ProtocolList, Reference

mail_list_validator = RegexValidator(r"[\w!#$%&'*+/=?^_`{|}~-]+(?:\.[\w!#$%&'*+/=?^_`{|}~-]+)*@(?:[\w](?:[\w-]*[\w])?\.)+[\w](?:[\w-]*[\w])?,",
                                     "Contacts must follow the format: abc@cornell.edu,def@cornell.edu,")

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

    workspace = forms.IntegerField(
        required=False
    )

    def clean(self):
        cleaned_data = super().clean()
        cd_inputs = cleaned_data.get("input_files")
        try:
            cd_inputs.encode("ascii")
        except UnicodeEncodeError:
            self.add_error("input_files", "Input files contain non-ASCII characters.")


class FetchRemoteProtocolForm(forms.Form):
    uid = forms.CharField(
        required=True,
        max_length=36,
    )


class QueryJobLogForm(forms.Form):
    job = forms.IntegerField(
        required=True
    )
    std_out = forms.IntegerField(
        required=False
    )


class JobManipulateForm(forms.Form):
    job = forms.IntegerField(
        required=True
    )
    step = forms.IntegerField(
        required=False
    )


class JobUpdateForm(forms.Form):
    id = forms.IntegerField(
        required=True
    )
    parameter = forms.CharField(
        required=True
    )


class UpdateProtocolDescForm(forms.Form):
    id = forms.ModelChoiceField(
        queryset=ProtocolList.objects.all(), required=True
    )
    parameter = forms.CharField(
        required=False
    )


class ProtocolManipulateForm(forms.Form):
    parent = forms.ModelChoiceField(
        queryset=ProtocolList.objects.all(), required=True
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
        required=True,
        max_length=500,
        widget=forms.TextInput(
            attrs={
                'class': u'input-block-level',
            }
        )
    )
    description = forms.CharField()


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
    env = forms.CharField(
        required=False
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


class StepPriorManipulateForm(forms.Form):
    step = forms.ModelChoiceField(
        queryset=Step.objects.all(), required=True
    )
    cpu_prior = forms.FloatField(
        required=False
    )
    mem_prior = forms.FloatField(
        required=False
    )
    disk_prior = forms.FloatField(
        required=False
    )


class StepEnvironmentManipulateForm(forms.Form):
    step = forms.ModelChoiceField(
        queryset=Step.objects.all(), required=True
    )
    env = forms.ModelChoiceField(
        queryset=VirtualEnvironment.objects.all(), required=False, empty_label=""
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


class CreateVEForm(forms.Form):
    name = forms.CharField(
        required=True,
        max_length=255,
    )
    value = forms.CharField(
        required=True,
        max_length=500,
    )


class CommentManipulateForm(forms.Form):
    trace = forms.CharField(
        required=True,
    )
    content = forms.CharField(
        required=True,
        max_length=500,
    )


class FileSupportForm(forms.Form):
    exp = forms.CharField(
        required=True,
    )
    support = forms.CharField(
        required=True,
        max_length=500,
    )
    file = forms.CharField(
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


class AddSampleForm(forms.Form):
    name = forms.CharField(max_length=500, required=True)
    file_path = forms.CharField(required=True)
    inner_path = forms.CharField(required=True)
    experiment = forms.IntegerField(required=True)
    attribute = forms.CharField(required=True)


class TarFilesForm(forms.Form):
    input_files = forms.CharField(max_length=5000, required=True)
    shared_with = forms.CharField(required=False, validators=[mail_list_validator, ])
    description = forms.CharField()


class SetWorkspaceForm(forms.Form):
    ws = forms.IntegerField(required=True)


class CreateReferenceForm(forms.ModelForm):
    class Meta:
        model = Reference
        exclude = ("user", )
        widgets = {
            "name": TextInput(attrs={"class": "form-control"}),
            "path": TextInput(attrs={"class": "form-control"}),
            "description": Textarea(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super(CreateReferenceForm, self).__init__(*args, **kwargs)


class CreateVEForm(forms.ModelForm):
    class Meta:
        model = VirtualEnvironment
        exclude = ("user", )
        labels = {
            "ve_type": "Type of environment",
        }
        widgets = {
            "name": TextInput(attrs={"class": "form-control"}),
            "ve_type": Select(attrs={"class": "form-control"}),
            "value": TextInput(attrs={"class": "form-control"}),
            "activation_command": TextInput(attrs={"class": "form-control"}),
        }
        help_texts = {
            "value": "If an environment is specified in a step, then the environment will be activated by <code>conda activate value</code> (for conda) before running the step.",
            "activation_command": "Optional. The environment managers (like <code>conda</code>) may not work in subshells, "
                                  "in this case, you may need to initiate the environment manager's settings first (<a href='https://github.com/conda/conda/issues/7980', target='_blank'>example</a>) "
                                  "then you can activate an environment. You can put the command to initiate the env here. "
                                  "Example: <code>source /home/user/anaconda3/etc/profile.d/conda.sh</code>",

        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super(CreateVEForm, self).__init__(*args, **kwargs)


class CreateWorkspaceForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ["name", "description"]
        widgets = {
            "name": TextInput(attrs={"class": "form-control"}),
            "description": Textarea(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super(CreateWorkspaceForm, self).__init__(*args, **kwargs)


class UpdateWorkspaceForm(forms.Form):
    id = forms.IntegerField(required=True)
    ws = forms.IntegerField(required=True)


class GenericDeleteForm(forms.Form):
    id = forms.IntegerField(required=True)


class FilterJobNameForm(forms.Form):
    job_name = forms.CharField()


class SearchSampleForm(forms.Form):
    name = forms.CharField(max_length=500, required=False)
    experiment = forms.ModelChoiceField(queryset=Experiment.objects.all(), required=False, empty_label="")
    attribute = forms.CharField(max_length=500, required=False)


class SearchJobAssociatedForm(forms.Form):
    files = forms.CharField(max_length=500, required=True)


class UpdateSampleForm(forms.Form):
    id = forms.IntegerField(required=True)
    parameter = forms.CharField(max_length=500, required=True)
