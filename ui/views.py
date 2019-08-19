from __future__ import print_function
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.template import loader
from django.http import HttpResponseRedirect, FileResponse, HttpResponse
from tools import error, success, delete_file, check_user_existence, handle_uploaded_file, \
    check_disk_quota_lock, build_json_protocol, os_to_int, get_disk_quota_info, build_json_reference
from worker.baseDriver import config_init, get_config, get_disk_free, get_disk_used, set_config, get_bioqueue_version
from .forms import SingleJobForm, JobManipulateForm, CreateProtocolForm, ProtocolManipulateForm, CreateStepForm, \
    StepManipulateForm, ShareProtocolForm, QueryLearningForm, CreateReferenceForm, BatchJobForm, \
    FetchRemoteProtocolForm, RefManipulateForm, StepOrderManipulateForm, CommentManipulateForm, FileSupportForm, \
    CreateVEForm
from .models import Queue, ProtocolList, Protocol, Prediction, References, VirtualEnvironment
import os
import re
from urllib import unquote


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
                        job_name=cd['job_name'],
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

            except Exception as e:
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
                    if cd["insert_to"] == -1:
                        step_amount = Protocol.objects.filter(parent=cd['parent']).count() + 1
                        step = Protocol(software=cd['software'],
                                        parameter=cd['parameter'],
                                        parent=protocol,
                                        user_id=request.user.id,
                                        step_order=step_amount,
                                        hash=m.hexdigest(),
                                        force_local=cd['force_local'])
                    else:
                        step = Protocol(software=cd['software'],
                                        parameter=cd['parameter'],
                                        parent=protocol,
                                        user_id=request.user.id,
                                        step_order=cd["insert_to"]+1,
                                        hash=m.hexdigest(),
                                        force_local=cd['force_local'])
                        to_update_steps = Protocol.objects.filter(parent=step.parent, step_order__gt=cd["insert_to"])
                        for tus in to_update_steps:
                            tus.step_order += 1
                            tus.save()
                    step.save()
                    return success('Your step have been created.')
                else:
                    return error('You are not owner of the protocol.')
            except Exception as e:
                return error(str(e))
    elif request.method == 'GET':
        template = loader.get_template('ui/add_step.html')
        if request.user.is_superuser:
            available_env = VirtualEnvironment.objects.all()
        else:
            available_env = VirtualEnvironment.objects.filter(user_id=request.user.id).all()
        context = {
            'parent': request.GET['protocol'],
            'user_envs': available_env,
        }
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
                                    except Exception as e:
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

            except Exception as e:
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
                    delete_job_file_tree(request, job.result)
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
                    delete_job_file_tree(request, job.result)
                else:
                    return error('Your are not the owner of the job.')
            return success('Ok')
        else:
            return error('Please choose an operation.')
    else:
        return success('abc')


def build_plain_protocol(request, protocol_id):
    """
    Convert protocol into a plain format
    :param request:
    :param protocol_id: int, protocol id
    :return: int or string, 1 means no such a protocol, 2 means no permission to access the protocol
    """
    protocol_data = dict()
    try:
        protocol_parent = ProtocolList.objects.get(id=protocol_id)
    except ProtocolList.DoesNotExist:
        # protocol doesn't exist
        return 1
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
                cpu_a = cpu_b = cpu_r = mem_a = mem_b = mem_r = disk_a = disk_b = disk_r = vrt_a = vrt_b = vrt_r = 0
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
                    elif equation.type == 4:
                        vrt_a = equation.a
                        vrt_b = equation.b
                        vrt_r = equation.r
                tmp = {
                    'software': step.software,
                    'parameter': step.parameter,
                    'hash': step.hash,
                    'step_order': step.step_order,
                    'cpu': get_config('env', 'cpu'),
                    'mem': get_config('env', 'memory'),
                    'os': os_to_int(),
                    'cpu_a': cpu_a,
                    'cpu_b': cpu_b,
                    'cpu_r': cpu_r,
                    'mem_a': mem_a,
                    'mem_b': mem_b,
                    'mem_r': mem_r,
                    'vrt_a': vrt_a,
                    'vrt_b': vrt_b,
                    'vrt_r': vrt_r,
                    'disk_a': disk_a,
                    'disk_b': disk_b,
                    'disk_r': disk_r,
                }
            except Exception as e:
                print(e)
                tmp = {
                    'software': step.software,
                    'parameter': step.parameter,
                    'hash': step.hash,
                }
            protocol_data['step'].append(tmp)
            protocol_data['reference'] = protocol_ref
        return protocol_data['name'], build_json_protocol(protocol_data)
    else:
        # no permission
        return 2


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
                try:
                    protocol_id_trace = ProtocolList.objects.get(id=protocol.id)
                except Exception as e:
                    return error(e)
                for index, software in enumerate(softwares):
                    if parameters[index]:
                        m = hashlib.md5()
                        m.update(software + ' ' + parameters[index].strip())
                        steps.append(Protocol(software=software,
                                              parameter=parameters[index],
                                              parent=protocol_id_trace,
                                              hash=m.hexdigest(),
                                              step_order=index+1,
                                              user_id=request.user.id))
                Protocol.objects.bulk_create(steps)
                return success('Your protocol have been created!')
            except Exception as e:
                return error(e)
        else:
            return error(str(protocol_form.errors))
    else:
        if request.user.is_superuser:
            available_env = VirtualEnvironment.objects.all()
        else:
            available_env = VirtualEnvironment.objects.filter(user_id=request.user.id).all()
        context = {'api_bus': get_config('program', 'api', 1),
                   'user_envs': available_env, }
        return render(request, 'ui/add_protocol.html', context)


@login_required
def create_reference_shortcut(request):
    reference_form = CreateReferenceForm(request.POST)
    if reference_form.is_valid():
        cd = reference_form.cleaned_data
        import base64
        if cd['source'] == 'upload' or cd['source'] == 'job':
            file_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), base64.b64decode(cd['path']))
            ref = References(
                name=cd['name'],
                path=file_path,
                description=cd['description'],
                user_id=request.user.id,
            )
            ref.save()
            return success(ref.id)
    else:
        return error(str(reference_form.errors))


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
                    delete_job_file_tree(request, job.result)
                    return success('Your job have been deleted.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception as e:
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


def delete_job_file_tree(request, f):
    try:
        job_path = os.path.join(os.path.join(get_config('env', 'workspace'), str(request.user.id)),
                                f)
        import shutil
        if os.path.exists(job_path):
            shutil.rmtree(job_path, ignore_errors=True)

    except Exception as e:
        print(e)


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
                    # update order
                    to_update_steps = Protocol.objects.filter(parent=step.parent, step_order__gt=step.step_order)
                    for tus in to_update_steps:
                        tus.step_order-=1
                        tus.save()
                    step.delete()
                    return success('Your step has been deleted.')
                else:
                    return error('You are not owner of the step.')
            except Exception as e:
                return error(e)
        else:
            return error('Unknown parameter.')
    else:
        return error('Method error.')


@login_required
def delete_upload_file(request, f):
    import base64
    file_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), base64.b64decode(f))
    delete_file(file_path)
    fm_path = os.path.join(get_config('env', 'workspace'), "file_comment", f)
    if os.path.exists(fm_path):
        delete_file(fm_path)

    return success('Deleted')


@login_required
def delete_ve(request):
    if request.method == 'GET':
        if 've' in request.GET:
            ve = VirtualEnvironment.objects.get(id=request.GET['ve'])
            if ve.check_owner(request.user.id) or request.user.is_superuser:
                ve.delete()
                return success('Your VE has been deleted.')
            else:
                return error('You are not owner of the VE.')
        else:
            return error('Missing parameter.')
    else:
        return error('Error Method.')


@login_required
def download_file(request, f):
    import base64
    file_path = os.path.join(get_config('env', 'workspace'),
                             str(request.user.id), base64.b64decode(f.replace('f/', '')))
    return download(file_path)


def download(file_path):
    try:
        response = FileResponse(open(file_path, 'rb'))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="{0}"'.format(os.path.basename(file_path))
        response['Content-Length'] = os.path.getsize(file_path)
        return response
    except Exception as e:
        return error(e)


@login_required
def export_protocol(request):
    if request.method == 'GET':
        if 'id' in request.GET:
            pname, protocol_text = build_plain_protocol(request, request.GET['id'])
            if protocol_text == 1:
                return error('Cannot find the protocol.')
            elif protocol_text == 2:
                return error('You are not owner of the protocol.')
            else:
                from django.http import StreamingHttpResponse
                response = StreamingHttpResponse(protocol_text)
                response['Content-Type'] = 'application/octet-stream'
                response['Content-Disposition'] = 'attachment;filename="{0}"'.format(str(pname + '.txt'))
                return response
        else:
            return error('Unknown parameter.')
    else:
        return error('Method error.')


@login_required
def file_support(request):
    if request.method == "GET":
        fs_form = FileSupportForm(request.GET)
        if fs_form.is_valid():
            cd = fs_form.cleaned_data
            from tools import get_maintenance_protocols
            protocol_name = "%s (%s)" % (cd["support"], cd["ext"])
            try:
                protocol_record = ProtocolList.objects.get(name=protocol_name, user_id=request.user.id)
            except ProtocolList.DoesNotExist:
                # build protocol
                if request.user.id == 0:
                    return error("Log in first.")
                protocol_parent = ProtocolList(name=protocol_name, user_id=request.user.id)
                protocol_parent.save()
                steps = list()
                maintenance_protocols = get_maintenance_protocols()
                step_order = 1
                if cd["support"] == "gg":
                    if cd["ext"] != "gz":
                        model = __import__("ui.maintenance_protocols.compress", fromlist=["gzip"])
                    else:
                        model = __import__("ui.maintenance_protocols.decompress", fromlist=["gunzip"])
                else:
                    if cd["support"] in maintenance_protocols:
                        model = __import__("ui.maintenance_protocols." + cd["support"], fromlist=[cd["support"]])
                    else:
                        return error("No support found.")
                step_order, sub_steps = model.get_sub_protocol(Protocol, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)

                try:
                    Protocol.objects.bulk_create(steps)
                    protocol_record = protocol_parent
                except:
                    protocol_parent.delete()
                    return error('Fail to save the protocol.')
            job = Queue(
                protocol_id=protocol_record.id,
                parameter=';',
                run_dir=get_config('env', 'workspace'),
                user_id=request.user.id,
                input_file="{Uploaded:%s}" % cd['file'],
                job_name="%s-%s" % (cd['support'], cd['file']),
            )
            try:
                job.save()
                return success('Push the task into job queue.')
            except:
                return error('Fail to save the job.')
        else:
            return error(str(fs_form.errors))


@login_required
def fetch_data(request):
    if request.method == "POST":
        from tools import get_maintenance_protocols
        protocol_name = "Fetch Data From EBI ENA"
        try:
            protocol_record = ProtocolList.objects.get(name=protocol_name, user_id=0)
        except ProtocolList.DoesNotExist:
            # build protocol
            protocol_parent = ProtocolList(name=protocol_name, user_id=0)
            protocol_parent.save()
            steps = list()
            maintenance_protocols = get_maintenance_protocols()
            # download
            step_order = 1
            if "download" not in maintenance_protocols:
                protocol_parent.delete()
                return error("No protocol to fetch the data")
            else:
                model = __import__("ui.maintenance_protocols.download", fromlist=["download"])
                step_order, sub_steps = model.get_sub_protocol(Protocol, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)
            # decompress
            if "gunzip" not in maintenance_protocols:
                protocol_parent.delete()
                return error("No protocol to decompress (gz) the data")
            else:
                model = __import__("ui.maintenance_protocols.gunzip", fromlist=["gunzip"])
                step_order, sub_steps = model.get_sub_protocol(Protocol, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)
            # move to user's uploads folder
            steps.append(Protocol(software="mv",
                                  parameter="{LastOutput} {UserUploads}",
                                  parent=protocol_parent,
                                  user_id=0,
                                  hash='c5f8bf22aff4c9fd06eb0844e6823d5f',
                                  step_order=step_order))
            try:
                Protocol.objects.bulk_create(steps)
                protocol_record = protocol_parent
            except:
                protocol_parent.delete()
                return error('Fail to save the protocol.')
        user_upload_dir = os.path.join(os.path.join(get_config('env', 'workspace'), str(request.user.id)), 'uploads')
        if not os.path.exists(user_upload_dir):
            try:
                os.makedirs(user_upload_dir)
            except:
                return error('Fail to create your uploads folder')
        from ena import query_download_link_from_ebi
        links = query_download_link_from_ebi(request.POST["acc"])
        if len(links) > 0:
            job = Queue(
                job_name=request.POST["acc"],
                protocol_id=protocol_record.id,
                parameter='UserUploads=%s;' % user_upload_dir,
                run_dir=get_config('env', 'workspace'),
                user_id=request.user.id,
                input_file=";".join(links),
            )
            try:
                job.save()
                return success("<br>".join(links))
            except:
                return error('Fail to save the job.')
        else:
            return error("No result found.")
    else:
        return render(request, 'ui/fetch_data.html')


@login_required
def fetch_learning(request):
    try:
        from urllib2 import urlopen
    except ImportError:
        from urllib.request import urlopen

    import json
    query_string = request.GET['hash'] + ',' + request.GET['type'] + ',' + str(get_config('env', 'cpu'))\
                   + ',' + str(get_config('env', 'memory')) + ',' + str(os_to_int())
    api_bus = get_config('program', 'api', 1)+'/Index/share/q/' + query_string
    try:
        res_data = urlopen(api_bus)
        res = json.loads(res_data.read())
        session_dict = {'hash': request.GET['hash'],
                        'type': request.GET['type'],
                        'a': res['a'],
                        'b': res['b'],
                        'r': res['r'], }
        request.session['learning'] = session_dict
        template = loader.get_template('ui/fetch_learning.html')
        context = {
            'step': res,
        }
        return success(template.render(context))
    except Exception as e:
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
                context = {
                    'hit': train,
                }
                return success(template.render(context))
            except Exception as e:
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
def import_protocol_by_fetch(request):
    if request.method == 'POST':
        form = FetchRemoteProtocolForm(request.POST)
        if form.is_valid():
            try:
                try:
                    from urllib2 import urlopen
                except ImportError:
                    from urllib.request import urlopen

                api_bus = get_config('program', 'api', 1) + '/Protocol/exportProtocolStdout?sig=' + request.POST['uid']
                try:
                    res_data = urlopen(api_bus)
                    protocol_raw = res_data.read()
                    import json
                    import hashlib
                    protocol_json = json.loads(protocol_raw)
                    if ProtocolList.objects.filter(name=protocol_json['name'], user_id=request.user.id).exists():
                        return error('Duplicate record!')
                    protocol = ProtocolList(name=protocol_json['name'], user_id=request.user.id)
                    protocol.save()
                    steps = []
                    predictions = []
                    try:
                        protocol_id_trace = ProtocolList.objects.get(id=protocol.id)
                    except Exception as e:
                        return error(e)
                    for step in protocol_json['step']:
                        m = hashlib.md5()
                        m.update(step['software'] + ' ' + step['parameter'].strip())
                        steps.append(Protocol(software=step['software'],
                                              parameter=step['parameter'],
                                              parent=protocol_id_trace,
                                              hash=m.hexdigest(),
                                              step_order=step['step_order'],
                                              user_id=request.user.id))
                        if 'cpu_a' in step.keys() and 'cpu_b' in step.keys() and 'cpu_r' in step.keys():
                            if 'cpu' in step.keys():
                                if step['cpu'] != get_config('env', 'cpu'):
                                    continue
                            if Prediction.objects.filter(step_hash=m.hexdigest(), type=3).exists():
                                continue
                            else:
                                predictions.append(Prediction(a=step['cpu_a'],
                                                              b=step['cpu_b'],
                                                              r=step['cpu_r'],
                                                              type=3,
                                                              step_hash=m.hexdigest()))
                        if 'mem_a' in step.keys() and 'mem_b' in step.keys() and 'mem_r' in step.keys():
                            if 'mem' in step.keys():
                                if step['mem'] != get_config('env', 'mem'):
                                    continue
                            if Prediction.objects.filter(step_hash=m.hexdigest(), type=2).exists():
                                continue
                            else:
                                predictions.append(Prediction(a=step['mem_a'],
                                                              b=step['mem_b'],
                                                              r=step['mem_r'],
                                                              type=2,
                                                              step_hash=m.hexdigest()))
                        if 'vrt_a' in step.keys() and 'vrt_b' in step.keys() and 'vrt_r' in step.keys():
                            if 'mem' in step.keys():
                                if step['mem'] != get_config('env', 'mem'):
                                    continue
                            if Prediction.objects.filter(step_hash=m.hexdigest(), type=2).exists():
                                continue
                            else:
                                predictions.append(Prediction(a=step['vrt_a'],
                                                              b=step['vrt_b'],
                                                              r=step['vrt_r'],
                                                              type=4,
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
                    ref_list = list()
                    for key, value in enumerate(protocol_json['reference']):
                        try:
                            _ = References.objects.get(name=value['name'], user_id=request.user.id)
                            ref_list.append({'name': value['name'],
                                             'description': value['description'],
                                             'status': 1, })
                        except:
                            ref_list.append({'name': value['name'],
                                             'description': value['description'],
                                             'status': 0, })
                    from django.template import RequestContext, loader
                    template = loader.get_template('ui/import_protocol.html')
                    return success(template.render({'ref_list': ref_list}))
                except Exception as e:
                    return error(e)
            except Exception as e:
                return error(e)
        else:
            return error(form.errors)
    else:
        return error('Error method')


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
                    try:
                        protocol_id_trace = ProtocolList.objects.get(id=protocol.id)
                    except Exception as e:
                        return error(e)
                    for step in protocol_json['step']:
                        m = hashlib.md5()
                        m.update(step['software'] + ' ' + step['parameter'].strip())
                        steps.append(Protocol(software=step['software'],
                                              parameter=step['parameter'],
                                              parent=protocol_id_trace,
                                              hash=m.hexdigest(),
                                              step_order=step['step_order'],
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
                                predictions.append(Prediction(a=step['mem_a'],
                                                              b=step['mem_b'],
                                                              r=step['mem_r'],
                                                              type=2,
                                                              step_hash=m.hexdigest()))
                        if 'vrt_a' in step.keys() and 'vrt_b' in step.keys() and 'vrt_r' in step.keys():
                            if 'mem' in step.keys():
                                if step['mem'] != get_config('env', 'mem'):
                                    continue
                            if Prediction.objects.filter(step_hash=m.hexdigest(), type=2).exists():
                                continue
                            else:
                                predictions.append(Prediction(a=step['vrt_a'],
                                                              b=step['vrt_b'],
                                                              r=step['vrt_r'],
                                                              type=4,
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
            except Exception as e:
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
def install_reference(request):
    if request.method == 'POST':
        import hashlib
        from json import loads
        from tools import get_maintenance_protocols
        ref_info = loads(request.POST['tool'])
        if type(ref_info['software']) == str or type(ref_info['software']) == unicode:
            protocol_name = ref_info['how_get'] + '_' + ref_info['compression'] + '_' + ref_info['software']
        else:
            protocol_name = ref_info['how_get'] + '_' + ref_info['compression'] + '_' + '_'.join(ref_info['software'])
        try:
            protocol_parent = ProtocolList.objects.get(name=protocol_name, user_id=0)
        except ProtocolList.DoesNotExist:
            protocol_parent = ProtocolList(name=protocol_name, user_id=0)
            protocol_parent.save()
            steps = list()
            maintenance_protocols = get_maintenance_protocols()
            step_order = 1
            # download
            if ref_info["how_get"] not in maintenance_protocols and ref_info["how_get"] != "n":
                protocol_parent.delete()
                return error("No protocol to fetch the data")
            else:
                model = __import__("ui.maintenance_protocols." + ref_info["how_get"], fromlist=[ref_info["how_get"]])
                step_order, sub_steps = model.get_sub_protocol(Protocol, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)
            # decompress
            if ref_info["compression"] not in maintenance_protocols and ref_info["compression"] != "n":
                protocol_parent.delete()
                return error("No protocol to decompress (%s) the data" % ref_info["compression"])
            else:
                if ref_info["compression"] != "n":
                    model = __import__("ui.maintenance_protocols." + ref_info["compression"],
                                       fromlist=[ref_info["compression"]])
                    step_order, sub_steps = model.get_sub_protocol(Protocol, protocol_parent, step_order)
                    for sub_step in sub_steps:
                        steps.append(sub_step)
            # post-decompression
            if type(ref_info['software']) == str or type(ref_info['software']) == unicode:
                step_order += 1
                m = hashlib.md5()
                m.update(ref_info['software'] + ' ' + ref_info['parameter'].strip())
                steps.append(Protocol(software=ref_info['software'],
                                      parameter=ref_info['parameter'].strip(),
                                      parent=protocol_parent,
                                      hash=m.hexdigest(),
                                      step_order=step_order,
                                      user_id=0))
            elif len(ref_info['software']) == len(ref_info['parameter']) and len(ref_info['software']) >= 1:
                for ind, software in enumerate(ref_info['software']):
                    step_order += 1
                    m = hashlib.md5()
                    m.update(software + ' ' + ref_info['parameter'][ind].strip())
                    steps.append(Protocol(software=software,
                                          parameter=ref_info['parameter'][ind].strip(),
                                          parent=protocol_parent,
                                          hash=m.hexdigest(),
                                          step_order=step_order,
                                          user_id=0))
            # move to user's ref folder
            steps.append(Protocol(software="mv",
                                  parameter="{CompileTargets} {UserRef}",
                                  parent=protocol_parent,
                                  user_id=0,
                                  hash='d885188751fc204ad7bbdf63fc6564df',
                                  step_order=step_order+1))
            Protocol.objects.bulk_create(steps)
        user_ref_dir = os.path.join(os.path.join(get_config('env', 'workspace'), str(request.user.id)), 'ref')
        if not os.path.exists(user_ref_dir):
            try:
                os.makedirs(user_ref_dir)
            except:
                return error('Fail to create your reference folder')
        if "target_files" in ref_info.keys():
            mv_parameter = " ".join(ref_info["target_files"].split(";"))
        else:
            mv_parameter = "{LastOutput}"
        job = Queue(
            protocol_id=protocol_parent.id,
            parameter='UserRef=%s;CompileTargets=%s' % (user_ref_dir, mv_parameter),
            run_dir=get_config('env', 'workspace'),
            user_id=request.user.id,
            input_file=ref_info["url"],
        )
        target_files = ref_info["target_files"].split(";")
        # create links to references
        ref_list = list()
        for target_file in target_files:
            ref_list.append(References(
                name=ref_info['name'],
                path=os.path.join(user_ref_dir, target_file),
                description=ref_info['description'],
                user_id=request.user.id,
            ))
        if len(ref_list) > 0:
            References.objects.bulk_create(ref_list)
        try:
            job.save()
            return success('Push the task into job queue.')
        except:
            return error('Fail to save the job.')
    else:
        api_bus = get_config('program', 'ref_repo_search_api', 1)
        tool_addr = get_config('program', 'ref_repo', 1)
        return render(request, 'ui/install_ref.html', {'ab': api_bus, 'ta': tool_addr})


@login_required
def install_tool(request):
    if request.method == 'POST':
        from json import loads
        from tools import get_maintenance_protocols
        import hashlib
        tool_info = loads(request.POST['tool'])
        # print(tool_info)
        protocol_name = tool_info['how_get']+'_'+tool_info['compression']+'_'+tool_info['compile_method']
        try:
            protocol_record = ProtocolList.objects.get(name=protocol_name, user_id=0)
        except ProtocolList.DoesNotExist:
            # build protocol
            protocol_parent = ProtocolList(name=protocol_name, user_id=0)
            protocol_parent.save()
            steps = list()
            maintenance_protocols = get_maintenance_protocols()
            step_order = 1
            # download
            if tool_info["how_get"] not in maintenance_protocols and tool_info["how_get"] != "n":
                protocol_parent.delete()
                return error("No protocol to fetch the data")
            else:
                model = __import__("ui.maintenance_protocols."+tool_info["how_get"], fromlist=[tool_info["how_get"]])
                step_order, sub_steps = model.get_sub_protocol(Protocol, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)
            # decompress
            if tool_info["compression"] not in maintenance_protocols and tool_info["compression"] != "n":
                protocol_parent.delete()
                return error("No protocol to decompress (%s) the data" % tool_info["compression"])
            else:
                if tool_info["compression"] != "n":
                    model = __import__("ui.maintenance_protocols."+tool_info["compression"], fromlist=[tool_info["compression"]])
                    step_order, sub_steps = model.get_sub_protocol(Protocol, protocol_parent, step_order)
                    for sub_step in sub_steps:
                        steps.append(sub_step)
            # compile
            if tool_info["compile_method"] not in get_maintenance_protocols() and tool_info["is_binary"] != "y":
                protocol_parent.delete()
                return error("No protocol to compile (%s) this tool." % tool_info["compile_method"])
            else:
                if tool_info["is_binary"] != "y":
                    worker_root = os.path.join(os.path.split(os.path.split(os.path.realpath(__file__))[0])[0], 'worker')
                    m = hashlib.md5()
                    compile_tool_command = '%s/compileTool.py -c %s -w {Workspace} -u {UserBin} -s %s' % \
                                           (worker_root, tool_info["compile_method"], tool_info["sub_folder"])
                    m.update('python ' + compile_tool_command.strip())
                    steps.append(Protocol(software='python',
                                          parameter=compile_tool_command,
                                          hash=m.hexdigest(),
                                          parent=protocol_parent,
                                          user_id=0,
                                          step_order=step_order))
                    step_order += 1
            # move to user's bin folder
            if tool_info["compile_targets"] != "n":
                steps.append(Protocol(software="mv",
                                      parameter="{CompileTargets} {UserBin}",
                                      parent=protocol_parent,
                                      user_id=0,
                                      hash='e6f31db5777dc687329b7390d4366676',
                                      step_order=step_order))
            try:
                Protocol.objects.bulk_create(steps)
                protocol_record = protocol_parent
            except:
                protocol_parent.delete()
                return error('Fail to save the protocol.')
        user_bin_dir = os.path.join(os.path.join(get_config('env', 'workspace'), str(request.user.id)), 'bin')
        if not os.path.exists(user_bin_dir):
            try:
                os.makedirs(user_bin_dir)
            except:
                return error('Fail to create your bin folder')
        if "compile_targets" in tool_info.keys():
            mv_parameter = " ".join(tool_info["compile_targets"].split(";"))
        else:
            mv_parameter = "{LastOutput}"
        job = Queue(
            protocol_id=protocol_record.id,
            parameter='UserBin=%s;CompileTargets=%s' % (user_bin_dir, mv_parameter),
            run_dir=get_config('env', 'workspace'),
            user_id=request.user.id,
            input_file=tool_info["url"],
        )
        try:
            job.save()
            return success('Push the task into job queue.')
        except:
            return error('Fail to save the job.')
    else:
        api_bus = get_config('program', 'tool_repo_search_api', 1)
        tool_addr = get_config('program', 'tool_repo', 1)
        return render(request, 'ui/install_tool.html', {'ab': api_bus, 'ta': tool_addr})


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


def page_info(page_model, page):
    try:
        items = page_model.page(page)
    except PageNotAnInteger:
        items = page_model.page(1)
    except EmptyPage:
        items = page_model.page(page_model.num_pages)
    return items


@login_required
def print_user_reference(request):
    result = list()
    try:
        refs = References.objects.filter(user_id=request.user.id)
        for ref in refs:
            result.append(ref.name)
        return build_json_reference(result)
    except:
        return build_json_reference(result)


@login_required
def query_job(request):
    if request.user.is_superuser:
        job_list = Queue.objects.order_by('-create_time').all()
    else:
        job_list = Queue.objects.filter(user_id=request.user.id).order_by('-create_time').all()
    paginator = Paginator(job_list, 12)

    page = request.GET.get('page')
    '''
    try:
        jobs = paginator.page(page)
    except PageNotAnInteger:
        jobs = paginator.page(1)
    except EmptyPage:
        jobs = paginator.page(paginator.num_pages)
    '''
    jobs = page_info(paginator, page)
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
                                'Workspace', 'UserBin', 'JobName']
            reference_list = References.objects.filter(user_id=request.user.id).all()
            pre_defined_keys.extend([reference.name for reference in reference_list])
            steps = Protocol.objects.filter(parent=protocol.id)
            wildcard_pattern = re.compile("\\{(.*?)\\}", re.IGNORECASE | re.DOTALL)
            for step in steps:
                for wildcard in re.findall(wildcard_pattern, step.parameter):
                    wildcard = wildcard.split(':')[0]
                    if wildcard.find(";") != -1:
                        continue
                    if wildcard.find(",") != -1:
                        continue
                    if wildcard not in pre_defined_keys:
                        user_defined_wildcards.append(wildcard)
    except:
        pass
    
    result = ''
    user_defined_wildcards = list(set(user_defined_wildcards))
    if len(user_defined_wildcards) > 0:
        result = '=;'.join(user_defined_wildcards)
        result += '=;'
    return success(result)


def query_protocol_atom(is_superuser, user_id, page):
    if is_superuser:
        protocol_list = ProtocolList.objects.all()
    else:
        protocol_list = ProtocolList.objects.filter(user_id=user_id).all()

    paginator = Paginator(protocol_list, 25)
    return page_info(paginator, page)


@login_required
def query_protocol(request):
    protocols = query_protocol_atom(request.user.is_superuser, request.user.id, request.GET.get('page'))
    return render(request, 'ui/list_protocol.html', {'protocol_list': protocols})


@login_required
def query_running_jobs(request):
    if request.user.is_superuser:
        running_job = Queue.objects.filter(status__gt=0).count()
    else:
        running_job = Queue.objects.filter(user_id=request.user.id).filter(status__gt=0).count()

    return success(running_job)


@login_required
def query_usage(request):
    """
    This function should only be called when the user is using IE8 or IE9
    :param request: 
    :return: 
    """
    try:
        from urllib2 import urlopen
    except ImportError:
        from urllib.request import urlopen

    api_bus = get_config('program', 'api', 1)+'/Kb/findSoftwareUsage?software='+request.POST['software']
    try:
        res_data = urlopen(api_bus)
        res = res_data.read()
        return HttpResponse(res)
    except Exception as e:
        return error(api_bus)


@login_required
def rerun_job(request):
    if request.method == 'POST':
        rerun_form = JobManipulateForm(request.POST)
        if rerun_form.is_valid():
            cd = rerun_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    delete_job_file_tree(request, job.result)
                    job.rerun_job()
                    return success('Your job will rerun soon.')
                else:
                    return error('Your are not the owner of the job.')
            except Exception as e:
                return error(e)
        else:
            return error(str(rerun_form.errors))
    else:
        return error('Method error')


@login_required
def mark_wrong_job(request):
    if request.method == 'POST':
        mw_form = JobManipulateForm(request.POST)
        if mw_form.is_valid():
            cd = mw_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id) or request.user.is_superuser:
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
def resume_job(request):
    if request.method == 'POST':
        terminate_form = JobManipulateForm(request.POST)
        if terminate_form.is_valid():
            cd = terminate_form.cleaned_data
            try:
                job = Queue.objects.get(id=cd['job'])
                if job.check_owner(request.user.id) or request.user.is_superuser:
                    rollback_to = int(cd['step']) - 2
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
def send_file_as_reference(request, f):
    import base64
    user_workspace = os.path.join(get_config('env', 'workspace'),
                             str(request.user.id))
    file_path = os.path.join(user_workspace, base64.b64decode(f.replace('f/', '')))
    ref_folder = os.path.join(user_workspace, 'refs')
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return error('Cannot find the file.')

    if not os.path.exists(ref_folder) or not os.path.isdir(ref_folder):
        try:
            os.makedirs(ref_folder)
        except Exception as e:
            return error(e)

    import shutil
    shutil.move(file_path, ref_folder)
    return success("")


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
            set_config('cluster', 'vrt', request.POST['job_vrt'])
            set_config('cluster', 'walltime', request.POST['job_wt'])
        else:
            set_config('cluster', 'type', '')
            set_config('cluster', 'cpu', '')
            set_config('cluster', 'queue', '')
            set_config('cluster', 'mem', '')
            set_config('cluster', 'vrt', '')
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
                'job_vrt': get_config('cluster', 'vrt'),
                'job_wt': get_config('cluster', 'walltime'),
                'rv': get_config('program', 'latest_version', 1),
                'cv': get_bioqueue_version(),
            }
        except Exception as e:
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
                        new_step.user_id = to_user
                        new_step.parent = new_protocol
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
                from worker.baseDriver import get_job_log
                return success(get_job_log(log_path))
            except Exception as e:
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
                    import operator
                    context = {
                        'user_files': sorted(user_files, key=lambda user_files : user_files['name']),
                    }
                    return success(template.render(context))
                else:
                    return error('Your are not the owner of the job.')
            except Exception as e:
                return error(e)
        else:
            return error(str(query_job_form.errors))
    else:
        return error('Method error')


@login_required
def show_learning(request):
    protocols = query_protocol_atom(request.user.is_superuser, request.user.id, request.GET.get('page'))
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
            context = {
                'step_list': step_list,
            }
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
                step_list = Protocol.objects.filter(parent=cd['parent']).all().order_by('step_order')
            else:
                step_list = Protocol.objects.filter(parent=cd['parent']).filter(user_id=request.user.id).all().order_by('step_order')
            template = loader.get_template('ui/show_steps.html')
            context = {
                'step_list': step_list,
                'parent': cd['parent'],
            }
            return success(template.render(context))
        else:
            return error(str(query_protocol_form.errors))
    else:
        return error('Method error.')


@login_required
def show_upload_files(request, special_type='uploads'):
    import time
    import base64
    user_path = os.path.join(get_config('env', 'workspace'), str(request.user.id), special_type)
    user_files = []
    if not os.path.exists(user_path):
        try:
            os.makedirs(user_path)
        except Exception as e:
            return render(request, 'ui/error.html', {'error_msg': e})

    for root, dirs, files in os.walk(user_path):
        for file_name in files:
            file_full_path = os.path.join(root, file_name)
            file_path = file_full_path.replace(user_path + '\\', '') \
                .replace(user_path + '/', '').replace(user_path, '')
            user_files.append(file_path)
    context = {'user_files': sorted(user_files)}
    return render(request, 'ui/show_uploads.html', context)


def check_file_comment(trace, prefix=""):
    """
    Check file comment
    :param trace:
    :param prefix: str, path to comments folder
    :return:
    """
    file_path = os.path.join(prefix, trace)
    if os.path.exists(file_path):
        fh = open(file_path, "r")
        comment = fh.read()
        fh.close()
    else:
        comment = ""
    return unquote(comment)


def show_workspace_files(user_id, special_type='uploads'):
    import time
    import base64

    user_files = []
    user_path = os.path.join(get_config('env', 'workspace'), str(user_id), special_type)
    fm_path = os.path.join(get_config('env', 'workspace'), 'file_comment')
    fs = config_init(2)

    if not os.path.exists(user_path):
        os.makedirs(user_path)

    for file_name in os.listdir(user_path):
        file_path = os.path.join(user_path, file_name)
        name, ext = os.path.splitext(file_name)
        tmp = dict()
        tmp['name'] = file_name
        tmp['file_size'] = os.path.getsize(file_path)
        tmp['file_create'] = time.ctime(os.path.getctime(file_path))
        tmp['trace'] = base64.b64encode(os.path.join(special_type, file_name))
        tmp['raw'] = os.path.join(special_type, file_name)
        tmp['comment'] = check_file_comment(tmp['trace'], fm_path)
        tmp['file_support'] = []
        ext = ext[1:].lower()
        tmp['ext'] = ext
        if ext in fs.sections():
            tmp['file_support'].extend(fs.items(ext))
        tmp['file_support'].extend(fs.items("generic"))
        user_files.append(tmp)
    user_files = sorted(user_files, key=lambda user_files: user_files['name'])
    return user_files


@login_required
def show_workspace(request):
    context = {'user_files': show_workspace_files(request.user.id, 'uploads'),
               'user_ref_files': show_workspace_files(request.user.id, 'refs'), }

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
            except Exception as e:
                return error(e)
        else:
            return error(str(terminate_form.errors))
    else:
        return error('Method error')


@staff_member_required
def update_bioqueue(request):
    try:
        update_py_path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/worker/update.py'
        update_command = 'python %s' % update_py_path
        if not os.system(update_command):
            return success('Your instance has been updated, please restart '
                           'the web server and queue service to apply the changes.')
        else:
            return error('An error occurred during the update process, please run update.py manually.')
    except Exception as e:
        return error(str(e))


@login_required
def update_comment(request):
    if request.method == 'GET':
        from urllib import unquote
        update_cmt_form = CommentManipulateForm(request.GET)
        if update_cmt_form.is_valid():
            cd = update_cmt_form.cleaned_data
            fm_path = os.path.join(get_config('env', 'workspace'), 'file_comment')

            with open(os.path.join(fm_path, cd['trace']), "w") as fh:
                fh.write(cd['content'])
                return success('Your comment has been updated.')
        else:
            return error(str(update_cmt_form.errors))
    else:
        return error('Method error')


@login_required
def update_parameter(request):
    if request.method == 'GET':
        from urllib import unquote
        update_parameter_form = StepManipulateForm(request.GET)
        if update_parameter_form.is_valid():
            cd = update_parameter_form.cleaned_data
            step = Protocol.objects.get(id=cd['id'])
            if (step.check_owner(request.user.id) or request.user.is_superuser):
                step.update_parameter(unquote(cd['parameter']))
                step.save()
                return success('Your step has been updated.')
            else:
                return error('Your are not owner of the step.')
        else:
            return error(str(update_parameter_form.errors))
    else:
        return error('Method error')


@login_required
def update_reference(request):
    if request.method == 'GET':
        from urllib import unquote
        update_ref_form = RefManipulateForm(request.GET)
        if update_ref_form.is_valid():
            cd = update_ref_form.cleaned_data
            ref = References.objects.get(id=cd['id'])
            if (ref.check_owner(request.user.id) or request.user.is_superuser):
                ref.path = unquote(cd['path'])
                ref.save()
                return success('Your reference has been updated.')
            else:
                return error('Your are not owner of the step.')
        else:
            return error(str(update_ref_form.errors))
    else:
        return error('Method error')


@login_required
def update_step_order(request):
    if request.method == 'GET':
        from urllib import unquote
        update_order_form = StepOrderManipulateForm(request.GET)
        if update_order_form.is_valid():
            cd = update_order_form.cleaned_data
            relations = list(filter(None, cd['step_order'].split(';')))
            error_tag = 0
            for relation in relations:
                step_id, new_order = relation.split('=')
                step = Protocol.objects.get(id=int(step_id), parent=int(cd['protocol']))
                if (step.check_owner(request.user.id) or request.user.is_superuser):
                    step.update_order(int(new_order))
                    step.save()
                else:
                    return error('Your are not owner of the step.')
            if not error_tag:
                return success('Your step has been updated.')
        else:
            return error(str(update_order_form.errors))
    else:
        return error('Method error')


@login_required
def upload_protocol(request):
    if request.method == 'GET':
        if 'id' in request.GET:
            pname, protocol_text = build_plain_protocol(request, request.GET['id'])
            if protocol_text == 1:
                return error('Cannot find the protocol.')
            elif protocol_text == 2:
                return error('You are not owner of the protocol.')
            else:
                from worker.feedback import feedback_protocol
                ret = feedback_protocol(request.user.email, protocol_text)
                if ret is not None:
                    if ret['status']:
                        return success(ret['info'])
                    else:
                        return error(ret['info'])

        else:
            return error('Unknown parameter.')
    else:
        return error('Method error.')


@login_required
def update_ve(request):
    if request.method == 'GET':
        update_ve_form = RefManipulateForm(request.GET)
        if update_ve_form.is_valid():
            cd = update_ve_form.cleaned_data
            ve = VirtualEnvironment.objects.get(id=cd['id'])
            if (ve.check_owner(request.user.id) or request.user.is_superuser):
                ve.value = unquote(cd['path'])
                ve.save()
                return success('Your VE has been updated.')
            else:
                return error('Your are not owner of the VE.')
        else:
            return error(str(update_ve_form.errors))
    else:
        return error('Method error')


@login_required
def virtual_environment(request):
    if request.method == 'POST':
        ve_form = CreateVEForm(request.POST)
        if ve_form.is_valid():
            cd = ve_form.cleaned_data
            if VirtualEnvironment.objects.filter(user_id=request.user.id, name=cd['name']).exists():
                return error('Duplicate record!')
            ve = VirtualEnvironment(name=cd['name'],
                                    value=cd['value'],
                                    user_id=request.user.id)
            ve.save()
            return success(ve.id)
        else:
            return error(str(ve_form.errors))
    else:
        if request.user.is_superuser:
            ve_list = VirtualEnvironment.objects.all()
        else:
            ve_list = VirtualEnvironment.objects.filter(user_id=request.user.id).all()
        return render(request, 'ui/manage_ve.html', {'ves': ve_list})
