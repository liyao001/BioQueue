from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.template import RequestContext, loader
from django.http import HttpResponseRedirect, FileResponse
from tools import error, success, delete_file, check_user_existence, handle_uploaded_file, \
    check_disk_quota_lock, build_json_protocol, os_to_int, get_disk_quota_info
from worker.baseDriver import get_config, get_disk_free, get_disk_used, set_config, get_bioqueue_version
from .forms import SingleJobForm, JobManipulateForm, CreateProtocolForm, ProtocolManipulateForm, CreateStepForm, \
    StepManipulateForm, ShareProtocolForm, QueryLearningForm, CreateReferenceForm, BatchJobForm
from .models import Queue, ProtocolList, Protocol, Prediction, References
import os
import re


@login_required
def add_job(request):
    if request.method == 'POST':
        job_form = SingleJobForm(request.POST)
        if job_form.is_valid():
            cd = job_form.cleaned_data
            try:
                if cd['parameter'].find(';') == -1:
                    cd['parameter'] += ';'

                protocol = ProtocolList.objects.get(id=cd['protocol'])
                if protocol.check_owner(request.user.id) or request.user.is_superuser:
                    job = Queue(
                        protocol_id=cd['protocol'],
                        parameter=cd['parameter'],
                        run_dir=get_config('env', 'workspace'),
                        user_id=request.user.id,
                        input_file=cd['input_files'],
                    )

                    if check_disk_quota_lock(request.user.id):
                        job.save()
                        return success('Successfully added job into queue.')
                    else:
                        return error('You have exceed the disk quota limit! Please delete some files!')
                else:
                    return error('You are not owner of the protocol.')

            except Exception, e:
                return error(e)
        return error(str(job_form.errors))
    else:
        if request.user.is_superuser:
            available_protocol = ProtocolList.objects.all()
        else:
            available_protocol = ProtocolList.objects.filter(user_id=request.user.id).all()

        dt, du, dp = get_disk_quota_info(request.user.id)
        return render(request, 'ui/add_job.html', {'form': SingleJobForm,
                                                   'user_protocols': available_protocol,
                                                   't_disk': dt,
                                                   'u_disk': du,
                                                   'disk_per': dp})


@login_required
def add_step(request):
    import hashlib
    if request.method == 'POST':
        step_form = CreateStepForm(request.POST)
        if step_form.is_valid():
            cd = step_form.cleaned_data
            try:
                protocol = ProtocolList.objects.get(id=cd['parent'])
                if protocol.check_owner(request.user.id) or request.user.is_superuser:
                    m = hashlib.md5()
                    m.update(cd['software'] + ' ' + cd['parameter'].strip())
                    step = Protocol(software=cd['software'],
                                    parameter=cd['parameter'],
                                    parent=cd['parent'],
                                    user_id=request.user.id,
                                    hash=m.hexdigest())
                    step.save()
                    return success('Your step have been created.')
                else:
                    return error('You are not owner of the protocol.')
            except Exception, e:
                return error(str(e))
    elif request.method == 'GET':
        template = loader.get_template('ui/add_step.html')
        context = RequestContext(request, {
            'parent': request.GET['protocol'],
        })
        return success(template.render(context))
    else:
        return error('Method error')


@login_required
def batch_job(request):
    if request.method == 'POST':
        form = BatchJobForm(request.POST, request.FILES)
        if form.is_valid():
            file_name = handle_uploaded_file(request.FILES['job_list'])
            try:
                protocol_cache = dict()
                with open(file_name) as f:
                    jobs = f.readlines()
                    job_list = []
                    for job in jobs:
                        configurations = job.split('\n')[0].split('\t')
                        if len(configurations) == 3:
                            if check_disk_quota_lock(request.user.id):
                                protocol_id = int(configurations[0])
                                if protocol_id not in protocol_cache:
                                    try:
                                        protocol = ProtocolList.objects.get(id=protocol_id)
                                        protocol_cache[protocol_id] = protocol.user_id
                                    except Exception, e:
                                        return render(request, 'ui/error.html', {'error_msg': e})
                                if protocol_cache[protocol_id] == request.user.id or request.user.is_superuser:
                                    job_list.append(
                                        Queue(input_file=configurations[1],
                                              parameter=configurations[2],
                                              run_dir=get_config('env', 'workspace'),
                                              protocol_id=protocol_id,
                                              user_id=request.user.id))
                                else:
                                    return render(request,
                                                  'ui/error.html',
                                                  {'error_msg': 'You are not the owner of the protocol(%s)' %
                                                                protocol_id})
                            else:
                                return render(request,
                                              'ui/error.html',
                                              {'error_msg': 'You have exceed the disk quota limit! Please delete some files!'})
                        else:
                            return render(request,
                                          'ui/error.html',
                                          {'error_msg': 'Your job list file must contain three columns.'})

                    Queue.objects.bulk_create(job_list)
                    return HttpResponseRedirect('/ui/query-job')

            except Exception, e:
                return render(request, 'ui/error.html', {'error_msg': e})
        else:
            return render(request,
                          'ui/error.html',
                          {'error_msg': str(form.errors)})


@login_required
def batch_operation(request):
    if request.method == 'POST':
        job_list = request.POST['jobs'].split(',')
        while '' in job_list:
            job_list.remove('')
        if request.POST['operation'] == 'd':
            for job_id in job_list:
                job = Queue.objects.get(id=job_id)

                if job.check_owner(request.user.id) or request.user.is_superuser:
                    job.delete()
                else:
                    return error('Your are not the owner of the job.')
            return success('Ok')
        elif request.POST['operation'] == 't':
            for job_id in job_list:
                job = Queue.objects.get(id=job_id)
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    job.terminate_job()
                else:
                    return error('Your are not the owner of the job.')
            return success('Ok')
        elif request.POST['operation'] == 'r':
            for job_id in job_list:
                job = Queue.objects.get(id=job_id)
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    job.rerun_job()
                else:
                    return error('Your are not the owner of the job.')
            return success('Ok')
        else:
            return error('Please choose an operation.')
    else:
        return success('abc')


@staff_member_required
def clean_dead_lock(request):
    Queue.objects.filter(status__gt=0).update(status=-3)
    Queue.objects.filter(status=-2).update(status=-3)
    return HttpResponseRedirect('/ui/settings')


@login_required
def create_protocol(request):
    import hashlib
    if request.method == 'POST':
        protocol_form = CreateProtocolForm(request.POST)
        if protocol_form.is_valid():
            try:
                cd = protocol_form.cleaned_data
                if ProtocolList.objects.filter(name=cd['name'], user_id=request.user.id).exists():
                    return error('Duplicate record!')
                protocol = ProtocolList(name=cd['name'], user_id=request.user.id)
                protocol.save()
                softwares = request.POST.getlist('software', '')
                parameters = request.POST.getlist('parameter', '')
                steps = []
                for index, software in enumerate(softwares):
                    if parameters[index]:
                        m = hashlib.md5()
                        m.update(software + ' ' + parameters[index].strip())
                        steps.append(Protocol(software=software,
                                              parameter=parameters[index],
                                              parent=protocol.id,
                                              hash=m.hexdigest(),
                                              user_id=request.user.id))
                Protocol.objects.bulk_create(steps)
                return success('Your protocol have been created!')
            except Exception, e:
                return error(e)
        else:
            return error(str(protocol_form.errors))
    else:
        return render(request, 'ui/add_protocol.html')


@login_required
def delete_job(request):
    if request.method == 'POST':
        terminate_form = JobManipulateForm(request.POST)
        if terminate_form.is_valid():
            cd = terminate_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    job.delete()
                    return success('Your job have been deleted.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception, e:
                return error(e)
        else:
            return error(str(terminate_form.errors))
    else:
        return error('Method error')


@login_required
def delete_job_file(request, f):
    import base64
    file_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), base64.b64decode(f))
    delete_file(file_path)

    return success('Deleted')


@login_required
def delete_protocol(request):
    if request.method == 'GET':
        if 'id' in request.GET:
            protocol_parent = ProtocolList.objects.get(id=int(request.GET['id']))
            if protocol_parent.check_owner(request.user.id) or request.user.is_superuser:
                protocol_parent.delete()
                steps = Protocol.objects.filter(parent=int(request.GET['id']))
                steps.delete()
                return success('Your protocol has been deleted.')
            else:
                return error('You are not owner of the protocol.')
        else:
            return error('Unknown parameter.')
    else:
        return error('Method error.')


@login_required
def delete_reference(request):
    if request.method == 'GET':
        if 'ref' in request.GET:
            ref = References.objects.get(id=request.GET['ref'])
            if ref.check_owner(request.user.id) or request.user.is_superuser:
                ref.delete()
                return success('Your reference has been deleted.')
            else:
                return error('You are not owner of the reference.')
        else:
            return error('Missing parameter.')
    else:
        return error('Error Method.')


@login_required
def delete_step(request):
    if request.method == 'GET':
        if 'id' in request.GET:
            try:
                step = Protocol.objects.get(id=int(request.GET['id']))
                if step.check_owner(request.user.id) or request.user.is_superuser:
                    step.delete()
                    return success('Your step has been deleted.')
                else:
                    return error('You are not owner of the step.')
            except Exception, e:
                return error(e)
        else:
            return error('Unknown parameter.')
    else:
        return error('Method error.')


@login_required
def delete_upload_file(request, f):
    import base64
    file_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), 'uploads', base64.b64decode(f))
    delete_file(file_path)

    return success('Deleted')


@login_required
def download_job_file(request, f):
    import base64
    file_path = os.path.join(get_config('env', 'workspace'),
                             str(request.user.id), base64.b64decode(f.replace('f/', '')))
    try:
        response = FileResponse(open(file_path, 'rb'))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="{0}"'.format(os.path.basename(file_path))
        response['Content-Length'] = os.path.getsize(file_path)
        return response
    except Exception, e:
        return error(e)


@login_required
def download_upload_file(request, f):
    import base64
    file_path = os.path.join(get_config('env', 'workspace'),
                             str(request.user.id), 'uploads', base64.b64decode(f.replace('f/', '')))
    try:
        response = FileResponse(open(file_path, 'rb'))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="{0}"'.format(os.path.basename(file_path))
        response['Content-Length'] = os.path.getsize(file_path)
        return response
    except Exception, e:
        return error(e)


@login_required
def export_protocol(request):
    if request.method == 'GET':
        if 'id' in request.GET:
            protocol_data = dict()
            try:
                protocol_parent = ProtocolList.objects.get(id=int(request.GET['id']))
            except ProtocolList.DoesNotExist:
                from django.http import Http404
                raise Http404("Protocol does not exist")
            protocol_data['name'] = protocol_parent.name
            protocol_data['step'] = []
            references = {}
            reference_list = References.objects.filter(user_id=request.user.id).all()
            protocol_ref = {}
            # references.extend([reference.name for reference in reference_list])
            for reference in reference_list:
                references[reference.name] = reference.description

            wildcard_pattern = re.compile("\\{(.*?)\\}", re.IGNORECASE | re.DOTALL)
            if protocol_parent.check_owner(request.user.id) or request.user.is_superuser:
                steps = Protocol.objects.filter(parent=int(request.GET['id']))
                for step in steps:
                    try:
                        for wildcard in re.findall(wildcard_pattern, step.parameter):
                            wildcard = wildcard.split(':')[0]
                            if wildcard in references.keys() and wildcard not in protocol_ref.keys():
                                protocol_ref[wildcard] = references[wildcard]
                        equations = Prediction.objects.filter(step_hash=step.hash)
                        cpu_a = cpu_b = cpu_r = mem_a = mem_b = mem_r = disk_a = disk_b = disk_r = 0
                        for equation in equations:
                            if equation.type == 1:
                                disk_a = equation.a
                                disk_b = equation.b
                                disk_r = equation.r
                            elif equation.type == 2:
                                mem_a = equation.a
                                mem_b = equation.b
                                mem_r = equation.r
                            elif equation.type == 3:
                                cpu_a = equation.a
                                cpu_b = equation.b
                                cpu_r = equation.r
                        tmp = {
                            'software': step.software,
                            'parameter': step.parameter,
                            'hash': step.hash,
                            'cpu': get_config('env', 'cpu'),
                            'mem': get_config('env', 'memory'),
                            'os': os_to_int(),
                            'cpu_a': cpu_a,
                            'cpu_b': cpu_b,
                            'cpu_r': cpu_r,
                            'mem_a': mem_a,
                            'mem_b': mem_b,
                            'mem_r': mem_r,
                            'disk_a': disk_a,
                            'disk_b': disk_b,
                            'disk_r': disk_r,
                        }
                    except Exception, e:
                        print e
                        tmp = {
                            'software': step.software,
                            'parameter': step.parameter,
                            'hash': step.hash,
                        }
                    protocol_data['step'].append(tmp)
                    protocol_data['reference'] = protocol_ref
                return build_json_protocol(protocol_data)
            else:
                return error('You are not owner of the protocol.')
        else:
            return error('Unknown parameter.')
    else:
        return error('Method error.')


@login_required
def fetch_learning(request):
    import urllib2
    import json
    query_string = request.GET['hash'] + ',' + request.GET['type'] + ',' + str(get_config('env', 'cpu'))\
                   + ',' + str(get_config('env', 'memory')) + ',' + str(os_to_int())
    api_bus = get_config('ml', 'api')+'/Index/share/q/' + query_string
    try:
        req = urllib2.Request(api_bus)
        res_data = urllib2.urlopen(req)
        res = json.loads(res_data.read())
        session_dict = {'hash': request.GET['hash'],
                        'type': request.GET['type'],
                        'a': res['a'],
                        'b': res['b'],
                        'r': res['r'], }
        request.session['learning'] = session_dict
        template = loader.get_template('ui/fetch_learning.html')
        context = RequestContext(request, {
            'step': res,
        })
        return success(template.render(context))
    except Exception, e:
        return error(api_bus)


@login_required
def get_learning_result(request):
    if request.method == 'GET':
        learning_form = QueryLearningForm(request.GET)
        if learning_form.is_valid():
            cd = learning_form.cleaned_data
            try:
                train = Prediction.objects.get(step_hash=cd['stephash'], type=cd['type'])
                template = loader.get_template('ui/get_learning_result.html')
                context = RequestContext(request, {
                    'hit': train,
                })
                return success(template.render(context))
            except Exception, e:
                return error(e)
        else:
            return error(str(learning_form.errors))
    else:
        return error('Error Method.')


@staff_member_required
def import_learning(request):
    if request.session['learning']:
        if request.session['learning']['a'] != 'no records':
            learn = Prediction(step_hash=request.session['learning']['hash'],
                               type=request.session['learning']['type'],
                               a=request.session['learning']['a'],
                               b=request.session['learning']['b'],
                               r=request.session['learning']['r'],)
            learn.save()
            return success('Imported.')
        else:
            return error('Can not import records!')
    else:
        return error('Error')


@login_required
def import_protocol(request):
    if request.method == 'POST':
        form = BatchJobForm(request.POST, request.FILES)
        if form.is_valid():
            file_name = handle_uploaded_file(request.FILES['job_list'])
            try:
                with open(file_name) as f:
                    protocol_raw = f.read()
                    import json
                    import hashlib
                    protocol_json = json.loads(protocol_raw)
                    if ProtocolList.objects.filter(name=protocol_json['name'], user_id=request.user.id).exists():
                        return error('Duplicate record!')
                    protocol = ProtocolList(name=protocol_json['name'], user_id=request.user.id)
                    protocol.save()
                    steps = []
                    predictions = []
                    for step in protocol_json['step']:
                        m = hashlib.md5()
                        m.update(step['software'] + ' ' + step['parameter'].strip())
                        steps.append(Protocol(software=step['software'],
                                              parameter=step['parameter'],
                                              parent=protocol.id,
                                              hash=m.hexdigest(),
                                              user_id=request.user.id))
                        if 'cpu_a' in step.keys() and 'cpu_b' in step.keys() and 'cpu_r' in step.keys():
                            if Prediction.objects.filter(step_hash=m.hexdigest(), type=3).exists():
                                continue
                            else:
                                predictions.append(Prediction(a=step['cpu_a'],
                                                              b=step['cpu_b'],
                                                              r=step['cpu_r'],
                                                              type=3,
                                                              step_hash=m.hexdigest()))
                        if 'mem_a' in step.keys() and 'mem_b' in step.keys() and 'mem_r' in step.keys():
                            if Prediction.objects.filter(step_hash=m.hexdigest(), type=2).exists():
                                continue
                            else:
                                predictions.append(Prediction(a=step['cpu_a'],
                                                              b=step['cpu_b'],
                                                              r=step['cpu_r'],
                                                              type=2,
                                                              step_hash=m.hexdigest()))
                        if 'disk_a' in step.keys() and 'disk_b' in step.keys() and 'disk_r' in step.keys():
                            if Prediction.objects.filter(step_hash=m.hexdigest(), type=1).exists():
                                continue
                            else:
                                predictions.append(Prediction(a=step['disk_a'],
                                                              b=step['disk_b'],
                                                              r=step['disk_r'],
                                                              type=1,
                                                              step_hash=m.hexdigest()))

                    Protocol.objects.bulk_create(steps)
                    if len(predictions):
                        Prediction.objects.bulk_create(predictions)
                    return HttpResponseRedirect('/ui/query-protocol')
            except Exception, e:
                return render(request, 'ui/error.html', {'error_msg': e})
        else:
            return render(request, 'ui/error.html', {'error_msg': str(form.errors)})
    else:
        return render(request, 'ui/error.html', {'error_msg': 'Error method'})


@login_required
def index(request):
    if request.user.is_superuser:
        running_job = Queue.objects.filter(status__gt=0).count()
    else:
        running_job = Queue.objects.filter(user_id=request.user.id).filter(status__gt=0).count()

    context = {'running_jobs': running_job}

    return render(request, 'ui/index.html', context)


@login_required
def manage_reference(request):
    if request.method == 'POST':
        reference_form = CreateReferenceForm(request.POST)
        if reference_form.is_valid():
            cd = reference_form.cleaned_data
            if References.objects.filter(user_id=request.user.id, name=cd['name']).exists():
                return error('Duplicate record!')
            ref = References(
                name=cd['name'],
                path=cd['path'],
                description=cd['description'],
                user_id=request.user.id,
            )
            ref.save()
            return success(ref.id)
        else:
            return error(str(reference_form.errors))
    else:
        if request.user.is_superuser:
            reference_list = References.objects.all()
        else:
            reference_list = References.objects.filter(user_id=request.user.id).all()
        return render(request, 'ui/manage_reference.html', {'references': reference_list})


@login_required
def query_job(request):
    if request.user.is_superuser:
        job_list = Queue.objects.order_by('-create_time').all()
    else:
        job_list = Queue.objects.filter(user_id=request.user.id).order_by('-create_time').all()
    paginator = Paginator(job_list, 25)

    page = request.GET.get('page')

    try:
        jobs = paginator.page(page)
    except PageNotAnInteger:
        jobs = paginator.page(1)
    except EmptyPage:
        jobs = paginator.page(paginator.num_pages)

    dt, du, dp = get_disk_quota_info(request.user.id)
    return render(request, 'ui/query_job.html', {'job_list': jobs, 't_disk': dt, 'u_disk': du, 'disk_per': dp})


@login_required
def query_job_parameter(request):
    import re
    parent = request.GET.get('parent')
    user_defined_wildcards = []
    try:
        protocol = ProtocolList.objects.get(id=parent)
        if protocol.check_owner(request.user.id) or request.user.is_superuser:
            pre_defined_keys = ['InputFile', 'LastOutput',
                                'Job', 'ThreadN',
                                'Output', 'LastOutput',
                                'Uploaded', 'Suffix',
                                'Workspace']
            reference_list = References.objects.filter(user_id=request.user.id).all()
            pre_defined_keys.extend([reference.name for reference in reference_list])
            steps = Protocol.objects.filter(parent=protocol.id)
            wildcard_pattern = re.compile("\\{(.*?)\\}", re.IGNORECASE | re.DOTALL)
            for step in steps:
                for wildcard in re.findall(wildcard_pattern, step.parameter):
                    wildcard = wildcard.split(':')[0]
                    if wildcard not in pre_defined_keys:
                        user_defined_wildcards.append(wildcard)
    except:
        pass
    user_defined_wildcards = list(set(user_defined_wildcards))
    if len(user_defined_wildcards) > 0:
        result = '=;'.join(user_defined_wildcards)
        result += '=;'
    return success(result)


@login_required
def query_protocol(request):
    if request.user.is_superuser:
        protocol_list = ProtocolList.objects.all()
    else:
        protocol_list = ProtocolList.objects.filter(user_id=request.user.id).all()
    paginator = Paginator(protocol_list, 25)

    page = request.GET.get('page')

    try:
        protocols = paginator.page(page)
    except PageNotAnInteger:
        protocols = paginator.page(1)
    except EmptyPage:
        protocols = paginator.page(paginator.num_pages)

    return render(request, 'ui/list_protocol.html', {'protocol_list': protocols})


@login_required
def rerun_job(request):
    if request.method == 'POST':
        rerun_form = JobManipulateForm(request.POST)
        if rerun_form.is_valid():
            cd = rerun_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    job.rerun_job()
                    return success('Your job will rerun soon.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception, e:
                return error(e)
        else:
            return error(str(rerun_form.errors))
    else:
        return error('Method error')


@login_required
def resume_job(request):
    if request.method == 'POST':
        terminate_form = JobManipulateForm(request.POST)
        if terminate_form.is_valid():
            cd = terminate_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    job.resume_job()
                    return success('Your job will be resumed soon.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception, e:
                return error(e)
        else:
            return error(str(terminate_form.errors))
    else:
        return error('Method error')


@staff_member_required
def settings(request):
    if request.method == 'POST':
        set_config('env', 'workspace', request.POST['path'])
        set_config('env', 'cpu', request.POST['cpu'])
        set_config('env', 'memory', request.POST['mem'])
        set_config('env', 'disk_quota', request.POST['dquota'])
        set_config('ml', 'confidence_weight_disk', request.POST['dcw'])
        set_config('ml', 'confidence_weight_mem', request.POST['mcw'])
        set_config('ml', 'confidence_weight_cpu', request.POST['ccw'])
        set_config('ml', 'threshold', request.POST['ccthr'])

        if request.POST['mailhost'] != '':
            set_config('mail', 'notify', 'on')
            set_config('mail', 'mail_host', request.POST['mailhost'])
            set_config('mail', 'mail_port', request.POST['mailport'])
            set_config('mail', 'mail_user', request.POST['mailuser'])
            set_config('mail', 'mail_password', request.POST['mailpassword'])
            if request.POST['protocol'] == 'ssl':
                set_config('mail', 'ssl', 'true')
            elif request.POST['protocol'] == 'tls':
                set_config('mail', 'tls', 'true')
        else:
            set_config('mail', 'notify', 'off')

        if request.POST['cluster_type'] != '':
            set_config('cluster', 'type', request.POST['cluster_type'])
            set_config('cluster', 'cpu', request.POST['job_cpu'])
            set_config('cluster', 'queue', request.POST['job_dest'])
            set_config('cluster', 'mem', request.POST['job_mem'])
            set_config('cluster', 'walltime', request.POST['job_wt'])
        else:
            set_config('cluster', 'type', '')
            set_config('cluster', 'cpu', '')
            set_config('cluster', 'queue', '')
            set_config('cluster', 'mem', '')
            set_config('cluster', 'walltime', '')

        return HttpResponseRedirect('/ui/settings')
    else:
        from worker.clusterSupport import get_cluster_models
        try:
            if get_config('mail', 'ssl') == 'true':
                mail_protocol = 'ssl'
            elif get_config('mail', 'tls') == 'true':
                mail_protocol = 'tls'
            else:
                mail_protocol = 'nm'

            configuration = {
                'run_folder': get_config('env', 'workspace'),
                'cpu': get_config('env', 'cpu'),
                'memory': get_config('env', 'memory'),
                'disk_quota': get_config('env', 'disk_quota'),
                'threshold': get_config('ml', 'threshold'),
                'disk_confidence_weight': get_config('ml', 'confidence_weight_disk'),
                'mem_confidence_weight': get_config('ml', 'confidence_weight_mem'),
                'cpu_confidence_weight': get_config('ml', 'confidence_weight_cpu'),
                'max_disk': round((get_disk_free(get_config('env', 'workspace'))
                                   +get_disk_used(get_config('env', 'workspace')))/1073741824),
                'free_disk': round(get_disk_free(get_config('env', 'workspace'))/1073741824),
                'mail_host': get_config('mail', 'mail_host'),
                'mail_port': get_config('mail', 'mail_port'),
                'mail_user': get_config('mail', 'mail_user'),
                'mail_password': get_config('mail', 'mail_password'),
                'mail_protocol': mail_protocol,
                'cluster_models': get_cluster_models(),
                'cluster_type': get_config('cluster', 'type'),
                'job_cpu': get_config('cluster', 'cpu'),
                'job_dest': get_config('cluster', 'queue'),
                'job_mem': get_config('cluster', 'mem'),
                'job_wt': get_config('cluster', 'walltime'),
            }
        except Exception, e:
            return render(request, 'ui/error.html', {'error_msg': e})

        return render(request, 'ui/settings.html', configuration)


@login_required
def share_with_peer(request):
    if request.method == 'POST':
        share_form = ShareProtocolForm(request.POST)
        if share_form.is_valid():
            cd = share_form.cleaned_data
            if cd['peer'] == request.user.username:
                return error('You can not share a protocol with yourself.')

            to_user = check_user_existence(cd['peer'])
            if to_user:
                from copy import deepcopy
                protocol = ProtocolList.objects.get(id=cd['pro'])
                if protocol.check_owner(request.user.id) or request.user.is_superuser:
                    new_protocol = deepcopy(protocol)
                    new_protocol.id = None
                    new_protocol.user_id = to_user
                    new_protocol.save()
                    steps = Protocol.objects.filter(parent=cd['pro'])
                    for step in steps:
                        new_step = deepcopy(step)
                        new_step.id = None
                        new_step.parent = new_protocol.id
                        new_step.save()
                    return success('You have successfully shared a protocol with a peer(%s).' % cd['peer'])
                else:
                    return error('Your are not owner of the protocol.')
            else:
                return error('The person you want to share with doesn\'t exist.')
        else:
            return error(str(share_form.errors))
    else:
        return error('Error Method.')


@login_required
def show_job_log(request):
    if request.method == 'POST':
        query_job_form = JobManipulateForm(request.POST)
        if query_job_form.is_valid():
            cd = query_job_form.cleaned_data
            log_path = os.path.join(get_config('env', 'log'), str(cd['job']))
            try:
                log_file = open(log_path, mode='r')
                log = log_file.readlines()
                log.reverse()
                log = log[:100]
                # log_content = [line+'<br />' for line in log]
                log_content = '<br />'.join(log)
                log_file.close()
                return success(log_content)
            except Exception, e:
                return error(e)
        else:
            return error(str(query_job_form.errors))
    else:
        return error('Method error')


@login_required
def show_job_folder(request):
    import time
    import base64
    if request.method == 'POST':
        query_job_form = JobManipulateForm(request.POST)
        if query_job_form.is_valid():
            cd = query_job_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    result_folder = job.get_result()
                    user_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), result_folder)
                    user_files = []
                    for root, dirs, files in os.walk(user_path):
                        for file_name in files:
                            file_full_path = os.path.join(root, file_name)
                            file_path = file_full_path.replace(user_path+'\\', '')\
                                .replace(user_path+'/', '').replace(user_path, '')
                            tmp = dict()
                            tmp['name'] = file_path
                            tmp['file_size'] = os.path.getsize(file_full_path)
                            tmp['file_create'] = time.ctime(os.path.getctime(file_full_path))
                            tmp['trace'] = base64.b64encode(os.path.join(result_folder, file_path))
                            user_files.append(tmp)
                    template = loader.get_template('ui/show_job_folder.html')
                    context = RequestContext(request, {
                        'user_files': user_files,
                    })
                    return success(template.render(context))
                else:
                    return error('Your are not the owner of the job.')
            except Exception, e:
                return error(e)
        else:
            return error(str(query_job_form.errors))
    else:
        return error('Method error')


@login_required
def show_learning(request):
    if request.user.is_superuser:
        protocol_list = ProtocolList.objects.all()
    else:
        protocol_list = ProtocolList.objects.filter(user_id=request.user.id).all()
    paginator = Paginator(protocol_list, 25)

    page = request.GET.get('page')

    try:
        protocols = paginator.page(page)
    except PageNotAnInteger:
        protocols = paginator.page(1)
    except EmptyPage:
        protocols = paginator.page(paginator.num_pages)

    return render(request, 'ui/show_learning.html', {'protocol_list': protocols})


@login_required
def show_learning_steps(request):
    if request.method == 'GET':
        if 'parent' in request.GET:
            if request.user.is_superuser:
                step_list = Protocol.objects.filter(parent=int(request.GET['parent'])).all()
            else:
                step_list = Protocol.objects.filter(parent=
                                                    int(request.GET['parent'])).filter(user_id=request.user.id).all()
            template = loader.get_template('ui/show_learning_steps.html')
            context = RequestContext(request, {
                'step_list': step_list,
            })
            return success(template.render(context))
        else:
            return error('Wrong parameter.')
    else:
        return error('Method error.')


@login_required
def show_step(request):
    if request.method == 'POST':
        query_protocol_form = ProtocolManipulateForm(request.POST)
        if query_protocol_form.is_valid():
            cd = query_protocol_form.cleaned_data
            if request.user.is_superuser:
                step_list = Protocol.objects.filter(parent=cd['parent']).all()
            else:
                step_list = Protocol.objects.filter(parent=cd['parent']).filter(user_id=request.user.id).all()
            template = loader.get_template('ui/show_steps.html')
            context = RequestContext(request, {
                'step_list': step_list,
            })
            return success(template.render(context))
        else:
            return error(str(query_protocol_form.errors))
    else:
        return error('Method error.')


@login_required
def show_upload_files(request):
    user_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), 'uploads')
    if not os.path.exists(user_path):
        try:
            os.makedirs(user_path)
        except Exception, e:
            return render(request, 'ui/error.html', {'error_msg': e})

    context = {'user_files': os.listdir(user_path)}
    return render(request, 'ui/show_uploads.html', context)


@login_required
def show_workspace(request):
    import time
    import base64

    user_files = []
    user_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), 'uploads')

    if not os.path.exists(user_path):
        os.makedirs(user_path)

    for file_name in os.listdir(user_path):
        file_path = os.path.join(user_path, file_name)
        tmp = dict()
        tmp['name'] = file_name
        tmp['file_size'] = os.path.getsize(file_path)
        tmp['file_create'] = time.ctime(os.path.getctime(file_path))
        tmp['trace'] = base64.b64encode(file_name)
        user_files.append(tmp)
    context = {'user_files': user_files}

    return render(request, 'ui/show_workspace.html', context)


@login_required
def terminate_job(request):
    if request.method == 'POST':
        terminate_form = JobManipulateForm(request.POST)
        if terminate_form.is_valid() or request.user.is_superuser:
            cd = terminate_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id):
                    job.terminate_job()
                    return success('Your job will be terminated soon.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception, e:
                return error(e)
        else:
            return error(str(terminate_form.errors))
    else:
        return error('Method error')


@staff_member_required
def update_bioqueue(request):
    import urllib2
    remote_address = get_config('program', 'latest_version')
    try:
        req = urllib2.Request(remote_address)
        res_data = urllib2.urlopen(req)
        remote_version = res_data.read()
        remote_version += " | <b>Current version:</b> " + get_bioqueue_version()
        return success(remote_version)
    except Exception, e:
        return error(str(remote_address))


@login_required
def update_parameter(request):
    if request.method == 'GET':
        from urllib import unquote
        update_parameter_form = StepManipulateForm(request.GET)
        if update_parameter_form.is_valid():
            cd = update_parameter_form.cleaned_data
            step = Protocol.objects.get(id=cd['id'])
            if (step.check_owner(request.user.id) or request.user.is_superuser) and step.check_parent(cd['parent']):
                step.update_parameter(unquote(cd['parameter']))
                step.save()
                return success('Your step has been updated.')
            else:
                return error('Your are not owner of the step.')
        else:
            return error(str(update_parameter_form.errors))
    else:
        return error('Method error')
