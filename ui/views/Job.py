#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 5/25/20
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.shortcuts import render
from django.template import loader
from django.http import HttpResponseRedirect, HttpResponse
from django.db.models import Q
from ..tools import error, success, delete_file, handle_uploaded_file, check_disk_quota_lock, get_disk_quota_info, \
    page_info
from worker.bases import get_config
from ..forms import *
from QueueDB.models import Job, ProtocolList, Step, Reference, FileArchive, Workspace, Audition
import os
import base64


@login_required
@permission_required("QueueDB.add_job", raise_exception=True)
def add_job(request):
    if request.method == 'POST':
        job_form = SingleJobForm(request.POST)
        if job_form.is_valid():
            cd = job_form.cleaned_data
            try:
                if cd['parameter'].find(';') == -1:
                    cd['parameter'] += ';'
                protocol = ProtocolList.objects.get(id=cd['protocol'])
                if protocol.check_owner(request.user.queuedb_profile_related.delegate):
                    try:
                        if 'workspace' in request.session:
                            ws = Workspace.objects.get(id=request.session['workspace'])
                        else:
                            ws = None
                    except Workspace.DoesNotExist:
                        ws = None

                    job = Job(
                        protocol_id=cd['protocol'],
                        protocol_ver=protocol.ver,
                        job_name=cd['job_name'],
                        parameter=cd['parameter'],
                        run_dir=get_config('env', 'workspace'),
                        user=request.user.queuedb_profile_related.delegate,
                        input_file=cd['input_files'],
                        workspace=ws,
                    )

                    if check_disk_quota_lock(request.user.queuedb_profile_related.delegate.id):
                        job.save()
                        Audition(operation="Created a new job",
                                 related_job=job,
                                 job_name=job.job_name,
                                 prev_par=job.parameter,
                                 new_par=job.parameter,
                                 prev_input=job.input_file,
                                 current_input=job.input_file,
                                 protocol=job.protocol.name,
                                 protocol_ver=job.protocol_ver,
                                 resume_point=job.resume,
                                 user=job.user
                                 ).save()
                        return success('Successfully added job into queue.')
                    else:
                        return error('You have exceed the disk quota limit! Please delete some files!')
                else:
                    return error('You are not owner of the protocol.')

            except Exception as e:
                return error(e)
        return error(str(job_form.errors))
    else:
        if request.user.is_staff:
            available_protocol = ProtocolList.objects.all()
        else:
            available_protocol = ProtocolList.objects.filter(
                Q(user=request.user.queuedb_profile_related.delegate) | Q(user=None)).all()

        dt, du, dp = get_disk_quota_info_with_cache(request.user.queuedb_profile_related.delegate.id)

        return render(request, 'ui/add_job.html', {'form': SingleJobForm,
                                                   'user_protocols': available_protocol,
                                                   't_disk': dt,
                                                   'u_disk': du,
                                                   'disk_per': dp})


@login_required
@permission_required("QueueDB.add_job", raise_exception=True)
def batch_job(request):
    if request.method == 'POST':
        form = BatchJobForm(request.POST, request.FILES)
        if form.is_valid():
            file_name = handle_uploaded_file(request.FILES['job_list'])
            try:
                protocol_cache = dict()
                try:
                    ws = Workspace.objects.get(id=request.session['workspace'])
                except Workspace.DoesNotExist:
                    ws = None
                with open(file_name) as f:
                    jobs = f.readlines()
                    job_list = []
                    for job in jobs:
                        configurations = job.split('\n')[0].split('\t')
                        if len(configurations) == 4:
                            if check_disk_quota_lock(request.user.queuedb_profile_related.delegate.id):
                                protocol_id = int(configurations[0])
                                if protocol_id not in protocol_cache:
                                    try:
                                        protocol = ProtocolList.objects.get(id=protocol_id)
                                        protocol_cache[protocol_id] = (int(protocol.user_id), protocol.ver)
                                    except Exception as e:
                                        return render(request, 'ui/error.html', {'error_msg': e})
                                if protocol_cache[
                                    protocol_id][0] == request.user.queuedb_profile_related.delegate.id or request.user.is_staff or \
                                        protocol_cache[protocol_id][0] == 0:
                                    job_list.append(
                                        Job(
                                            protocol_id=protocol_id,
                                            protocol_ver=protocol_cache[protocol_id][1],
                                            job_name=configurations[1],
                                            input_file=configurations[2],
                                            parameter=configurations[3],
                                            run_dir=get_config('env', 'workspace'),
                                            user=request.user.queuedb_profile_related.delegate,
                                            workspace=ws))
                                else:
                                    return render(request,
                                                  'ui/error.html',
                                                  {'error_msg': 'You are not the owner of the protocol(%s)' %
                                                                protocol_id})
                            else:
                                return render(request,
                                              'ui/error.html',
                                              {
                                                  'error_msg': 'You have exceed the disk quota limit! Please delete some files!'})
                        else:
                            return render(request,
                                          'ui/error.html',
                                          {'error_msg': 'Your job list file must contain three columns.'})

                    Job.objects.bulk_create(job_list)
                    return HttpResponseRedirect('/ui/query-job')

            except Exception as e:
                return render(request, 'ui/error.html', {'error_msg': e})
        else:
            return render(request,
                          'ui/error.html',
                          {'error_msg': str(form.errors)})


@login_required
@permission_required("QueueDB.delete_job", raise_exception=True)
@permission_required("QueueDB.change_job", raise_exception=True)
def batch_operation(request):
    if request.method == 'POST':
        job_list = request.POST['jobs'].split(',')
        while '' in job_list:
            job_list.remove('')
        if request.POST['operation'] == 'd':
            for job_id in job_list:
                job = Job.objects.get(id=job_id)

                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    job.delete()
                    if job.result is not None:
                        delete_job_file_tree(request, job.result)
                else:
                    return error('Your are not the owner of the job.')
            return success('Ok')
        elif request.POST['operation'] == 't':
            for job_id in job_list:
                job = Job.objects.get(id=job_id)
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    job.terminate_job()
                else:
                    return error('Your are not the owner of the job.')
            return success('Ok')
        elif request.POST['operation'] == 'r':
            for job_id in job_list:
                job = Job.objects.get(id=job_id)
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    job.rerun_job()
                    if job.result is not None:
                        delete_job_file_tree(request, job.result)
                else:
                    return error('Your are not the owner of the job.')
            return success('Ok')
        else:
            return error('Please choose an operation.')
    else:
        return error('Unsupported operation')


def get_disk_quota_info_with_cache(uid, cache_lifetime=1800):
    """
    Get disk quota information with Cache
    Parameters
    ----------
    uid : str or int
        User ID
    cache_lifetime : int
        Lifetime of the cache, by default 1800s

    Returns
    -------
    dt : int
        All available disk quota
    du : int
        Used disk quota
    dp : int
        Percent of disk quota used
    """
    disk_quota_cache_key = "{0}.disk_quota_cache".format(str(uid))
    quota_info = cache.get(disk_quota_cache_key)
    if quota_info is not None:
        dt, du, dp = quota_info
    else:
        dt, du, dp = get_disk_quota_info(uid)
        cache.set(disk_quota_cache_key, (dt, du, dp), cache_lifetime)
    return dt, du, dp


@login_required
@permission_required("QueueDB.delete_job", raise_exception=True)
def delete_job(request):
    if request.method == 'POST':
        terminate_form = JobManipulateForm(request.POST)
        if terminate_form.is_valid():
            cd = terminate_form.cleaned_data
            # try:
            if True:
                job = Job.objects.get(id=cd['job'])
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    n_archive = 0
                    # try:
                    if True:
                        archives = FileArchive.objects.filter(job=job)
                        n_archive = len(archives)
                        if n_archive == 0:
                            job.delete()
                            delete_job_file_tree(request, job.result)
                            return success('Your job have been deleted.')
                        else:
                            return error("Job is under protection.(%d dependent archives)" % n_archive)
                    # except Exception as e:
                    #     return error(e)

                else:
                    return error('Your are not the owner of the job.')
            # except Exception as e:
            #     return error(e)
        else:
            return error(str(terminate_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.delete_job", raise_exception=True)
def delete_job_file(request, f):
    file_path = os.path.join(get_config('env', 'workspace'), str(request.user.queuedb_profile_related.delegate.id),
                             base64.b64decode(f).decode())
    delete_file(file_path)

    return success('Deleted')


def delete_job_file_tree(request, f):
    try:
        if f is not None and f != "":
            job_path = os.path.join(os.path.join(get_config('env', 'workspace'),
                                                 str(request.user.queuedb_profile_related.delegate.id)), f)
            import shutil
            if os.path.exists(job_path):
                shutil.rmtree(job_path, ignore_errors=True)

    except Exception as e:
        print(e)


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
def get_job_list(request):
    import json
    if request.user.is_staff:
        job_list = Job.objects.filter(job_name__icontains=request.GET["q"])
    else:
        job_list = Job.objects.filter(user=request.user.queuedb_profile_related.delegate, job_name__icontains=request.GET["q"])
    pre_result = {"results": []}
    for job in job_list:
        pre_result["results"].append({"text": job.job_name, "id": job.id})
    return HttpResponse(json.dumps(pre_result), content_type='application/json')


def get_job_files(job_id, user_id, super_user):
    import time
    try:
        user_files = []
        job = Job.objects.get(id=job_id)
        if job.check_owner(user_id):
            result_folder = job.get_result()
            if result_folder is None:  # doesn't have output
                return user_files
            user_path = os.path.join(job.run_dir, str(job.user_id), result_folder)
            print(user_path)

            for root, dirs, files in os.walk(user_path):
                for file_name in files:
                    if file_name == ".snapshot.ini":
                        continue
                    file_full_path = os.path.join(root, file_name)
                    file_path = file_full_path.replace(user_path + '\\', '') \
                        .replace(user_path + '/', '').replace(user_path, '')
                    tmp = dict()
                    tmp['name'] = file_path
                    tmp['file_size'] = os.path.getsize(file_full_path)
                    tmp['file_create'] = time.ctime(os.path.getctime(file_full_path))
                    tmp['trace'] = base64.b64encode(os.path.join(result_folder, file_path).encode()).decode()
                    user_files.append(tmp)
            return user_files
        else:
            return "Your are not the owner of the job."
    except Exception as e:
        return e


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
def get_job_file_list(request):
    import json
    file_list = get_job_files(request.GET["id"], request.user.queuedb_profile_related.delegate.id, request.user.is_superuser)
    return HttpResponse(json.dumps(file_list), content_type='application/json')


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
def query_job(request):
    try:
        ws = Workspace.objects.get(id=request.session['workspace'])
    except Workspace.DoesNotExist:
        ws = None
        request.session['workspace'] = -1
    except KeyError:
        ws = None
        request.session['workspace'] = -1
    job_name_filter = ''
    if request.GET.get("job_name"):
        JNF = FilterJobNameForm(request.GET)
        if JNF.is_valid():
            jnf_cd = JNF.cleaned_data
            job_name_filter = jnf_cd["job_name"]
    if request.user.is_superuser:
        job_list = Job.objects.order_by('-create_time').filter(job_name__icontains=job_name_filter)
    else:
        if ws is not None:
            job_list = Job.objects.filter(user=request.user.queuedb_profile_related.delegate,
                                          workspace=ws,
                                          job_name__icontains=job_name_filter).order_by('-create_time').all()
        else:
            job_list = Job.objects.filter(user=request.user.queuedb_profile_related.delegate,
                                          job_name__icontains=job_name_filter).order_by('-create_time').all()
    # job_list = Job.objects.filter(job_name__icontains=request.GET["q"])
    only_running_flag = 0
    only_wrong_flag = 0
    if "only_running" in request.COOKIES and request.COOKIES["only_running"] == '1':
        job_list = job_list.filter(status__gt=0)
        only_running_flag = 1
    elif "only_wrong" in request.COOKIES and request.COOKIES["only_wrong"] == '1':
        job_list = job_list.filter(status=-3)
        only_running_flag = 0
        only_wrong_flag = 1
    paginator = Paginator(job_list, 12)

    page = request.GET.get('page')
    jobs = page_info(paginator, page)

    dt, du, dp = get_disk_quota_info_with_cache(request.user.queuedb_profile_related.delegate.id, cache_lifetime=1800)
    return render(request, 'ui/query_job.html', {'job_list': jobs, 't_disk': dt, 'u_disk': du, 'disk_per': dp,
                                                 'workspaces': Workspace.objects.filter(
                                                     user=request.user.queuedb_profile_related.delegate),
                                                 'only_running': only_running_flag,
                                                 'only_wrong': only_wrong_flag,
                                                 'paginator': paginator,
                                                 'current_page': page})


@login_required
@permission_required("QueueDB.view_step", raise_exception=True)
def query_job_parameter(request):
    import re
    parent = request.GET.get('parent')
    user_defined_wildcards = []
    protocol_description = ''
    try:
        protocol = ProtocolList.objects.get(id=parent)
        if protocol.check_owner(request.user.queuedb_profile_related.delegate):
            protocol_description = protocol.description
            pre_defined_keys = ['InputFile', 'LastOutput',
                                'Job', 'ThreadN',
                                'Output', 'LastOutput',
                                'Uploaded', 'Suffix',
                                'Workspace', 'UserBin', 'JobName']
            reference_list = Reference.objects.filter(Q(user=request.user.queuedb_profile_related.delegate) | Q(user=None)).all()
            pre_defined_keys.extend([reference.name for reference in reference_list])
            steps = Step.objects.filter(parent=protocol.id)
            wildcard_pattern = re.compile("\\{\\{(.*?)\\}\\}", re.IGNORECASE | re.DOTALL)
            for step in steps:
                for wildcard in re.findall(wildcard_pattern, step.parameter):
                    wildcard = wildcard.split(':')[0]
                    if wildcard.find(";") != -1:
                        continue
                    if wildcard.find(",") != -1:
                        continue
                    if wildcard not in pre_defined_keys:
                        user_defined_wildcards.append(wildcard)
    except Exception as e:
        return error(e)

    result = dict(par='', desc=protocol_description)
    user_defined_wildcards = list(set(user_defined_wildcards))
    if len(user_defined_wildcards) > 0:
        result['par'] = '=;'.join(user_defined_wildcards)
        result['par'] += '=;'
    return success(result)


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
def query_running_jobs(request):
    msgs = []
    if request.user.is_superuser:
        running_job = Job.objects.filter(status__gt=0).count()
    else:
        running_job = Job.objects.filter(user=request.user.queuedb_profile_related.delegate).filter(status__gt=0).count()
    if request.user.queuedb_profile_related.delegate.queuedb_profile_related.notification_enabled:
        # qs = Notification.objects.filter(user=request.user.queuedb_profile_related.delegate)
        qs = []
        for note in qs:
            msgs.append(note.msg)
        # qs.delete()

    return success({"n": running_job, "m": msgs})


@login_required
@permission_required("QueueDB.change_job", raise_exception=True)
def rerun_job(request):
    if request.method == 'POST':
        rerun_form = JobManipulateForm(request.POST)
        if rerun_form.is_valid():
            cd = rerun_form.cleaned_data
            try:
                job = Job.objects.get(id=cd['job'])
                prev_protocol_ver = job.protocol_ver
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    if job.result is not None:
                        delete_job_file_tree(request, job.result)
                    job.rerun_job()
                    if prev_protocol_ver == job.protocol.ver:
                        return success('Your job will rerun soon.')
                    else:
                        return success('Your job will rerun soon (protocol modified).')
                else:
                    return error('Your are not the owner of the job.')
            except Exception as e:
                return error(e)
        else:
            return error(str(rerun_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_job", raise_exception=True)
def mark_wrong_job(request):
    if request.method == 'POST':
        mw_form = JobManipulateForm(request.POST)
        if mw_form.is_valid():
            cd = mw_form.cleaned_data
            try:
                job = Job.objects.get(id=cd['job'])
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    # delete_job_file_tree(request, job.result)
                    job.status = -3
                    job.save()
                    return success('Job status changed')
                else:
                    return error('Your are not the owner of the job.')
            except Exception as e:
                return error(e)
        else:
            return error(str(mw_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_job", raise_exception=True)
def resume_job(request):
    if request.method == 'POST':
        terminate_form = JobManipulateForm(request.POST)
        if terminate_form.is_valid():
            cd = terminate_form.cleaned_data
            try:
                job = Job.objects.get(id=cd['job'])
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    rollback_to = max(int(cd['step']), 0)
                    if rollback_to <= job.resume:
                        job.resume_job(rollback_to)
                    else:
                        job.resume_job(job.resume)
                    return success('Your job will be resumed soon.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception as e:
                return error(e)
        else:
            return error(str(terminate_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
def show_job_log(request):
    if request.method == 'POST':
        query_job_form = QueryJobLogForm(request.POST)
        if query_job_form.is_valid():
            cd = query_job_form.cleaned_data
            suffix = ".log" if cd["std_out"] else ".err"
            log_path = os.path.join(get_config('env', 'log'), str(cd['job'])+suffix)
            try:
                from worker.bases import get_job_log
                return success(get_job_log(log_path))
            except Exception as e:
                return error(e)
        else:
            return error(str(query_job_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
def show_job_folder(request):
    if request.method == 'POST':
        query_job_form = JobManipulateForm(request.POST)
        if query_job_form.is_valid():
            cd = query_job_form.cleaned_data
            user_files = get_job_files(cd["job"], request.user.queuedb_profile_related.delegate.id, request.user.is_superuser)
            if type(user_files) is list:
                template = loader.get_template('ui/show_job_folder.html')
                import operator
                context = {
                    'user_files': sorted(user_files, key=lambda user_files: user_files['name']),
                    'jid': cd["job"]
                }
                return success(template.render(context))
            else:
                return error(user_files)
        else:
            return error(str(query_job_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_job", raise_exception=True)
def terminate_job(request):
    if request.method == 'POST':
        terminate_form = JobManipulateForm(request.POST)
        if terminate_form.is_valid() or request.user.is_superuser:
            cd = terminate_form.cleaned_data
            try:
                job = Job.objects.get(id=cd['job'])
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    job.terminate_job()
                    return success('Your job will be terminated soon.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception as e:
                return error(e)
        else:
            return error(str(terminate_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_job", raise_exception=True)
def update_job_inputs(request):
    if request.method == 'GET':
        update_job_form = JobUpdateForm(request.GET)
        if update_job_form.is_valid():
            cd = update_job_form.cleaned_data
            try:
                import urllib.parse
                job = Job.objects.get(id=cd['id'])
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    job.update_inputs(urllib.parse.unquote(cd['parameter']))
                else:
                    return error('Your are not owner of the Job.')
            except Job.DoesNotExist:
                return error('Workspace doesn\'t exist.')
            return success('Job\'s inputs have been updated.')

        else:
            return error(str(update_job_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_job", raise_exception=True)
def update_job_parameter(request):
    if request.method == 'GET':
        update_job_form = JobUpdateForm(request.GET)
        if update_job_form.is_valid():
            cd = update_job_form.cleaned_data
            try:
                import urllib.parse
                job = Job.objects.get(id=cd['id'])
                if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    job.update_parameter(urllib.parse.unquote(cd['parameter']))
                else:
                    return error('Your are not owner of the Job.')
            except Job.DoesNotExist:
                return error('Workspace doesn\'t exist.')
            return success('Job\'s parameters have been updated.')

        else:
            return error(str(update_job_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_workspace", raise_exception=True)
def update_workspace(request):
    if request.method == 'POST':
        update_ws_form = UpdateWorkspaceForm(request.POST)
        if update_ws_form.is_valid():
            cd = update_ws_form.cleaned_data
            job = Job.objects.get(id=cd['id'])
            if job.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                try:
                    if cd['ws'] != -1:
                        ws = Workspace.objects.get(id=cd['ws'], user=request.user.queuedb_profile_related.delegate)
                    else:
                        ws = None
                    job.workspace = ws
                    job.save()
                except Job.DoesNotExist:
                    return error('Workspace doesn\'t exist.')
                return success('Job\'s workspace has been updated.')
            else:
                return error('Your are not owner of the Job.')
        else:
            return error(str(update_ws_form.errors))
    else:
        return error('Method error')
