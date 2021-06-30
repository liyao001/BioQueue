#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 5/29/20
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.db.models import Q
from django.template.loader import render_to_string
import operator
from functools import reduce
from ..tools import error, success, page_info
from worker.bases import get_config
from ..forms import *
from QueueDB.models import Experiment, Sample
import os
import base64
import time


def _sample_render(raw_samples):
    """
    Atom operator for rendering registered samples
    This function will apply base64 decode to the field of `inner_path`

    Parameters
    ----------
    raw_samples : list/tuple/django.db.models.QuerySet
        Raw samples to be converted/rendered

    Returns
    -------
    translated_samples : list of dictionaries
        Each dictionary holds a record of a sample
            name: name of the sample
            create_time: time of creation
            trace: files' absolute paths (base64 encoded)
            inner: files' relative paths (to the upload folder, base64 encoded)
            raw: files' absolute paths
            attribute: comments
            file_support: available operations to data generated from this type of experiment
            exp: name of experiment
    """
    translated_samples = []
    experiment_cache = {}
    for sample in raw_samples:
        if sample.experiment.id not in experiment_cache:
            try:
                t = [fs.split("=") for fs in sample.experiment.file_support.split(";") if
                     fs != ""]
            except:
                t = []
            experiment_cache[sample.experiment.id] = t
        real_path = ""
        file_names = ";".join(map(lambda x: base64.b64decode(x).decode(), sample.inner_path.split(";")))
        if sample.user.queuedb_profile_related.delegate.queuedb_profile_related.upload_folder != "":
            real_path = ";".join(map(lambda x: "uploads/" + os.path.split(base64.b64decode(x).decode())[1],
                                     sample.inner_path.split(";")))
        else:
            real_path = file_names
        translated_samples.append({
            "id": sample.pk,
            "name": sample.name,
            "create_time": sample.create_time,
            "trace": sample.file_path,
            "inner": sample.inner_path,
            "raw": file_names,
            "rp": real_path,
            "attribute": sample.attribute,
            "file_support": experiment_cache[sample.experiment.id],
            "exp": sample.experiment.name,
        })
    return translated_samples


@login_required
@permission_required("QueueDB.view_sample", raise_exception=True)
def query_job_samples(request):
    if request.method == "POST":
        query_form = SearchJobAssociatedForm(request.POST)
        if query_form.is_valid():
            cd = query_form.cleaned_data
            try:
                if len(cd["files"]) > 0:
                    query_files = [base64.b64decode(qf.encode()).decode() for qf in set(cd["files"].split(";")) if
                                   qf != ""]
                    samples = Sample.objects.filter(user=request.user.queuedb_profile_related.delegate)
                    samples = samples.filter(reduce(operator.or_,
                                                    (Q(file_path__contains=qf) for qf in query_files)))
                    translated_samples = _sample_render(samples)
                return success(render_to_string("ui/registered_sample_cards.html", {"samples": translated_samples}))
            except Exception as e:
                return error(e)
        else:
            return error(str(query_form.errors))


@login_required
@permission_required("QueueDB.add_sample", raise_exception=True)
def register_sample(request):
    if request.method == 'POST':
        reg_form = AddSampleForm(request.POST)
        if reg_form.is_valid():
            cd = reg_form.cleaned_data
            try:
                exp = Experiment.objects.get(id=cd['experiment'])
                try:
                    Sample.objects.get(user=request.user.queuedb_profile_related.delegate, file_path=cd["file_path"])
                    return error("Sample already exist!")
                except Sample.DoesNotExist:
                    # if user prefers not to use the default upload folder
                    # then BioQueue will create symbolic links in the uploads
                    # folder for user
                    if request.user.queuedb_profile_related.upload_folder != "":
                        first_order_soft_link = os.path.join(get_config('env', 'workspace'),
                                                             str(request.user.queuedb_profile_related.delegate.id),
                                                             "OVERRIDE_UPLOAD")
                        if not os.path.exists(first_order_soft_link) or not os.path.islink(first_order_soft_link):
                            os.symlink(request.user.queuedb_profile_related.upload_folder, first_order_soft_link)
                        expected_upload_path = os.path.join(get_config('env', 'workspace'),
                                                            str(request.user.queuedb_profile_related.delegate.id),
                                                            "uploads")
                        for file in cd["inner_path"].split(";"):
                            real_path = base64.b64decode(file).decode("utf-8")
                            dst_path = os.path.join(expected_upload_path,
                                                    os.path.split(real_path)[1])

                            if not os.path.exists(dst_path):
                                os.symlink(src=os.path.join("../OVERRIDE_UPLOAD", real_path),
                                           dst=dst_path)
                            else:
                                return error("This sample is already registered")

                    Sample(name=cd["name"],
                           file_path=";".join(
                               [base64.b64decode(fp.encode()).decode() for fp in cd["file_path"].split(";") if
                                fp != ""]),
                           user=request.user.queuedb_profile_related.delegate, experiment=exp,
                           attribute=cd["attribute"],
                           inner_path=cd["inner_path"]).save()
                    return success("Sample registered")
                except Sample.MultipleObjectsReturned:
                    return error("Duplicate records!")
            except Exception as e:
                return error(e)
        else:
            return error(str(reg_form.errors))
    else:
        block_files = Sample.objects.filter(user=request.user.queuedb_profile_related.delegate)
        block_file_real = set()
        for bf in block_files:
            for rbf in bf.inner_path.split(";"):
                block_file_real.add(rbf)
        if request.user.queuedb_profile_related.upload_folder != "":
            ufs = show_workspace_files(request.user.queuedb_profile_related.delegate.id,
                                       request.user.queuedb_profile_related.upload_folder,
                                       block_files=block_file_real)
        else:
            ufs = show_workspace_files(request.user.queuedb_profile_related.delegate.id, 'uploads',
                                       block_files=block_file_real)
        context = {'user_files': ufs,
                   'user_ref_files': show_workspace_files(request.user.queuedb_profile_related.delegate.id, 'refs'),
                   'experiments': Experiment.objects.filter(), }

        return render(request, 'ui/register_sample.html', context)


@login_required
@permission_required("QueueDB.view_sample", raise_exception=True)
def show_upload_files(request, special_type='uploads'):
    user_path = os.path.join(get_config('env', 'workspace'), str(request.user.queuedb_profile_related.delegate.id), special_type)
    user_files = []
    if not os.path.exists(user_path):
        try:
            os.makedirs(user_path)
        except Exception as e:
            return render(request, 'ui/error.html', {'error_msg': e})

    for root, dirs, files in os.walk(user_path):
        for file_name in files:
            warn_msg = []
            file_full_path = os.path.join(root, file_name)
            file_name_warning = 0
            if file_full_path.find(" ") != -1:
                file_name_warning = 1
                warn_msg.append("White space found in the file path")
            else:
                try:
                    file_full_path.encode("ascii")
                except UnicodeEncodeError:
                    file_name_warning = 1
                    warn_msg.append("Non-ASCII code found in the file path")
            file_path = file_full_path.replace(user_path + '\\', '') \
                .replace(user_path + '/', '').replace(user_path, '')
            user_files.append((file_path, file_name_warning, ";".join(warn_msg)))
    context = {'user_files': sorted(user_files, key=lambda x: x[0])}
    return render(request, 'ui/show_uploads.html', context)


def show_workspace_files(user_id, special_type='uploads', block_files=None):
    import time
    user_files = []
    if special_type != "uploads" and special_type != "refs":
        user_path = special_type
    else:
        user_path = os.path.join(get_config('env', 'workspace'), str(user_id), special_type)

    if not os.path.exists(user_path):
        os.makedirs(user_path)

    for root, dirs, files in os.walk(user_path):
        for file_name in files:
            file_full_path = os.path.join(root, file_name)

            subs = ""
            if root != user_path:
                subs = root.replace(user_path + "/", "")
            tmp = dict()
            tmp['name'] = os.path.join(subs, file_name)
            tmp['file_size'] = os.path.getsize(file_full_path)
            tmp['file_create'] = time.ctime(os.path.getctime(file_full_path))
            tmp['trace'] = base64.b64encode(os.path.join(special_type, tmp['name']).encode()).decode()
            tmp['raw'] = base64.b64encode(tmp['name'].encode()).decode()
            if block_files is not None and tmp['raw'] not in block_files:
                user_files.append(tmp)
    user_files = sorted(user_files, key=lambda user_files: user_files['name'])
    return user_files


@login_required
@permission_required("QueueDB.view_sample", raise_exception=True)
def show_workspace(request):
    searching_name = ""
    searching_note = ""
    searching_exp = ""
    if request.user.is_staff:
        samples = Sample.objects.order_by("-create_time").filter()
    else:
        samples = Sample.objects.filter(user=request.user.queuedb_profile_related.delegate).order_by(
            "-create_time")
    if request.method == "POST":
        ss_form = SearchSampleForm(request.POST)
        if ss_form.is_valid():
            cd = ss_form.cleaned_data
            try:
                if cd["name"] is not None and cd["name"] != "":
                    samples = samples.filter(name__contains=cd["name"])
                    searching_name = cd["name"]
                if cd["experiment"] is not None:
                    samples = samples.filter(experiment=cd["experiment"])
                    searching_exp = cd["experiment"].id
                if cd["attribute"] is not None and cd["attribute"] != "":
                    samples = samples.filter(attribute__contains=cd["attribute"])
                    searching_note = cd["attribute"]
            except Exception as e:
                return error(e)
        else:
            return error(str(ss_form.errors))
    paginator = Paginator(samples, 10)
    page = request.GET.get("page")

    selected_samples = page_info(paginator, page)
    translated_samples = _sample_render(selected_samples)
    context = {"samples": translated_samples, "raw": selected_samples,
               "s_name": searching_name, "s_note": searching_note,
               "s_exp": searching_exp,
               "experiments": Experiment.objects.all()}
    return render(request, 'ui/show_samples.html', context)


@login_required
@permission_required("QueueDB.change_sample", raise_exception=True)
def update_sample_attr(request):
    """
    Update sample's attribute

    Parameters
    ----------
    request :

    Returns
    -------

    """
    if request.method == "POST":
        form = UpdateSampleForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                sample = Sample.objects.get(pk=cd["id"])
                if request.user.is_superuser or sample.user == request.user.queuedb_profile_related.delegate:
                    sample.attribute = cd["parameter"]
                    sample.save()
                    return success("Updated")
                else:
                    return error("You don't have permission to update information about this sample")
            except Exception as e:
                return error(str(e))
