#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 5/25/20
# @todo: A priors for steps
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.template import loader
from django.http import HttpResponseRedirect
from django.db.models import Q
from ..tools import error, success, handle_uploaded_file, build_json_protocol, os_to_int, page_info
from worker.bases import get_config
from ..forms import *
from QueueDB.models import ProtocolList, Step, Prediction, Reference, VirtualEnvironment
import re
import hashlib
from urllib.parse import unquote
from urllib.request import urlopen, Request


def archive_protocol(request, pid):
    name, protocol_in_json = build_plain_protocol(request, int(pid), False)
    sig = hashlib.md5(protocol_in_json.encode("utf-8")).hexdigest()
    filename = "{pid}_{sig}.txt".format(pid=pid, sig=sig)
    fh = open("protocol_dumps/{filename}".format(filename=filename), "w")
    fh.write(protocol_in_json)
    fh.close()
    protocol_obj = ProtocolList.objects.get(id=int(pid))
    protocol_obj.ver = sig
    protocol_obj.save()


@login_required
@permission_required("QueueDB.add_step", raise_exception=True)
def add_step(request):
    import hashlib
    if request.method == 'POST':
        step_form = CreateStepForm(request.POST)
        if step_form.is_valid():
            cd = step_form.cleaned_data
            try:
                protocol = ProtocolList.objects.get(id=cd['parent'])
                if protocol.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    m = hashlib.md5((cd['software'] + ' ' + cd['parameter'].strip()).encode())
                    env = cd["env"]
                    if env != "":
                        try:
                            env = VirtualEnvironment.objects.get(id=int(env))
                        except:
                            env = None
                    else:
                        env = None
                    if cd["insert_to"] == -1:
                        step_amount = Step.objects.filter(parent=cd['parent']).count() + 1
                        step = Step(software=cd['software'],
                                        parameter=cd['parameter'],
                                        version_check=cd['version_check'],
                                        parent=protocol,
                                        user=request.user.queuedb_profile_related.delegate,
                                        step_order=step_amount,
                                        hash=m.hexdigest(),
                                        force_local=cd['force_local'],
                                        env=env)
                    else:
                        step = Step(software=cd['software'],
                                        parameter=cd['parameter'],
                                        version_check=cd['version_check'],
                                        parent=protocol,
                                        user=request.user.queuedb_profile_related.delegate,
                                        step_order=cd["insert_to"] + 1,
                                        hash=m.hexdigest(),
                                        force_local=cd['force_local'],
                                        env=env)
                        to_update_steps = Step.objects.filter(parent=step.parent, step_order__gt=cd["insert_to"])
                        for tus in to_update_steps:
                            tus.step_order += 1
                            tus.save()
                    step.save()
                    archive_protocol(request, protocol.id)
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
            available_env = VirtualEnvironment.objects.filter(user=request.user.queuedb_profile_related.delegate).all()
        context = {
            'parent': request.GET['protocol'],
            'user_envs': available_env,
        }
        return success(template.render(context))
    else:
        return error('Method error')


def build_plain_protocol(request, protocol_id, stand_alone=True):
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
        return '', 1
    if protocol_parent.check_owner(request.user.queuedb_profile_related.delegate):
        steps = Step.objects.filter(parent=protocol_parent.id)
    else:
        return '', 2

    protocol_data['name'] = protocol_parent.name
    protocol_data['step'] = []
    for step in steps:
        tmp = {
            'software': step.software,
            'parameter': step.parameter,
            'hash': step.hash,
            'step_order': step.step_order,
        }
        protocol_data['step'].append(tmp)
    if stand_alone:
        references = {}
        reference_list = Reference.objects.filter(user=request.user.queuedb_profile_related.delegate).all()
        protocol_ref = {}
        # references.extend([reference.name for reference in reference_list])
        for reference in reference_list:
            references[reference.name] = reference.description

        wildcard_pattern = re.compile("\\{\\{(.*?)\\}\\}", re.IGNORECASE | re.DOTALL)
        for i, step in enumerate(steps):
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
                protocol_data['step'][i]['cpu'] = get_config('env', 'cpu')
                protocol_data['step'][i]['memory'] = get_config('env', 'memory')
                protocol_data['step'][i]['os'] = os_to_int()
                protocol_data['step'][i]['cpu_a'] = cpu_a
                protocol_data['step'][i]['cpu_b'] = cpu_b
                protocol_data['step'][i]['cpu_r'] = cpu_r
                protocol_data['step'][i]['mem_a'] = mem_a
                protocol_data['step'][i]['mem_b'] = mem_b
                protocol_data['step'][i]['mem_r'] = mem_r
                protocol_data['step'][i]['vrt_a'] = vrt_a
                protocol_data['step'][i]['vrt_b'] = vrt_b
                protocol_data['step'][i]['vrt_r'] = vrt_r
                protocol_data['step'][i]['disk_a'] = disk_a
                protocol_data['step'][i]['disk_b'] = disk_b
                protocol_data['step'][i]['disk_r'] = disk_r
            except:
                pass
            # protocol_data['step'].append(tmp)
            protocol_data['reference'] = protocol_ref
    return protocol_data['name'], build_json_protocol(protocol_data)


@login_required
@permission_required("QueueDB.add_protocollist", raise_exception=True)
@permission_required("QueueDB.add_step", raise_exception=True)
def create_protocol(request):
    import hashlib
    if request.method == 'POST':
        protocol_form = CreateProtocolForm(request.POST)
        if protocol_form.is_valid():
            try:
                cd = protocol_form.cleaned_data
                if ProtocolList.objects.filter(name=cd['name'], user=request.user.queuedb_profile_related.delegate).exists():
                    return error('Duplicate record!')
                protocol = ProtocolList(name=cd['name'], description=cd['description'],
                                        user=request.user.queuedb_profile_related.delegate)
                protocol.save()
                softwares = request.POST.getlist('software', '')
                parameters = request.POST.getlist('parameter', '')
                version_checks = request.POST.getlist('version_check', '')
                virtual_environments = request.POST.getlist('env', '')
                steps = []
                try:
                    protocol_id_trace = ProtocolList.objects.get(id=protocol.id)
                except Exception as e:
                    return error(e)
                for index, software in enumerate(softwares):
                    if parameters[index]:
                        m = hashlib.md5((software + ' ' + parameters[index].strip()).encode())
                        env = virtual_environments[index]
                        if env != "":
                            try:
                                env = VirtualEnvironment.objects.get(id=int(env))
                            except:
                                env = None
                        else:
                            env = None
                        steps.append(Step(software=software,
                                              parameter=parameters[index],
                                              version_check=version_checks[index],
                                              env=env,
                                              parent=protocol_id_trace,
                                              hash=m.hexdigest(),
                                              step_order=index + 1,
                                              user=request.user.queuedb_profile_related.delegate))
                Step.objects.bulk_create(steps)
                archive_protocol(request, protocol_id_trace.id)
                return success('Your protocol have been created!')
            except Exception as e:
                return error(e)
        else:
            return error(str(protocol_form.errors))
    else:
        if request.user.is_superuser:
            available_env = VirtualEnvironment.objects.all()
        else:
            available_env = VirtualEnvironment.objects.filter(user=request.user.queuedb_profile_related.delegate).all()
        context = {'api_bus': get_config('program', 'api', 1),
                   'user_envs': available_env, }
        return render(request, 'ui/add_protocol.html', context)


@login_required
@permission_required("QueueDB.delete_protocollist", raise_exception=True)
def delete_protocol(request):
    if request.method == 'GET':
        if 'id' in request.GET:
            protocol_parent = ProtocolList.objects.get(id=int(request.GET['id']))
            if protocol_parent.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                protocol_parent.delete()
                steps = Step.objects.filter(parent=int(request.GET['id']))
                steps.delete()
                return success('Your protocol has been deleted.')
            else:
                return error('You are not owner of the protocol.')
        else:
            return error('Unknown parameter.')
    else:
        return error('Method error.')


@login_required
@permission_required("QueueDB.delete_step", raise_exception=True)
def delete_step(request):
    if request.method == "GET":
        if "id" in request.GET:
            try:
                step = Step.objects.get(id=int(request.GET['id']))
                pid = step.parent
                if step.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    # update order
                    to_update_steps = Step.objects.filter(parent=pid, step_order__gt=step.step_order)
                    for tus in to_update_steps:
                        tus.step_order -= 1
                        tus.save()
                    step.delete()
                    archive_protocol(request, pid.id)
                    return success("Your step has been deleted.")
                else:
                    return error("You are not owner of the step.")
            except Exception as e:
                return error(e)
        else:
            return error("Unknown parameter.")
    else:
        return error("Method error.")


@login_required
@permission_required("QueueDB.view_protocollist", raise_exception=True)
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
@permission_required("QueueDB.add_protocollist", raise_exception=True)
@permission_required("QueueDB.add_step", raise_exception=True)
def import_protocol_by_fetch(request):
    if request.method == 'POST':
        form = FetchRemoteProtocolForm(request.POST)
        if form.is_valid():
            try:
                api_bus = get_config('program', 'api', 1) + '/Protocol/exportProtocolStdout?sig=' + request.POST['uid']
                try:
                    req = Request(api_bus, headers={"User-Agent": "BioQueue-client"})
                    protocol_raw = urlopen(req).read()
                    import json
                    import hashlib
                    protocol_json = json.loads(protocol_raw.decode("utf-8"))
                    if ProtocolList.objects.filter(name=protocol_json['name'],
                                                   user=request.user.queuedb_profile_related.delegate).exists():
                        return error('Duplicate record!')
                    protocol = ProtocolList(name=protocol_json['name'], user=request.user.queuedb_profile_related.delegate)
                    protocol.save()
                    steps = []
                    predictions = []
                    try:
                        protocol_id_trace = ProtocolList.objects.get(id=protocol.id)
                    except Exception as e:
                        return error(e)
                    for step in protocol_json['step']:
                        m = hashlib.md5((step['software'] + ' ' + step['parameter'].strip()).encode())
                        # m.update(step['software'] + ' ' + step['parameter'].strip())
                        steps.append(Step(software=step['software'],
                                              parameter=step['parameter'],
                                              parent=protocol_id_trace,
                                              hash=m.hexdigest(),
                                              step_order=step['step_order'],
                                              user=request.user.queuedb_profile_related.delegate))
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

                    Step.objects.bulk_create(steps)
                    if len(predictions):
                        Prediction.objects.bulk_create(predictions)
                    ref_list = list()
                    for key, value in enumerate(protocol_json['reference']):
                        try:
                            _ = Reference.objects.get(name=value['name'], user=request.user.queuedb_profile_related.delegate)
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
@permission_required("QueueDB.add_protocollist", raise_exception=True)
@permission_required("QueueDB.add_step", raise_exception=True)
def import_protocol(request):
    if request.method == 'POST':
        form = BatchJobForm(request.POST, request.FILES)
        if form.is_valid():
            file_name = handle_uploaded_file(request.FILES['job_list'])
            try:
                with open(file_name) as f:
                    protocol_raw = f.read()
                    import json
                    protocol_json = json.loads(protocol_raw)
                    if ProtocolList.objects.filter(name=protocol_json['name'],
                                                   user=request.user.queuedb_profile_related.delegate).exists():
                        return error('Duplicate record!')
                    protocol = ProtocolList(name=protocol_json['name'], user=request.user.queuedb_profile_related.delegate)
                    protocol.save()
                    steps = []
                    predictions = []
                    try:
                        protocol_id_trace = ProtocolList.objects.get(id=protocol.id)
                    except Exception as e:
                        return error(e)
                    for step in protocol_json['step']:
                        m = hashlib.md5((step['software'] + ' ' + step['parameter'].strip()).encode())
                        # m.update(step['software'] + ' ' + step['parameter'].strip())
                        steps.append(Step(software=step['software'],
                                              parameter=step['parameter'],
                                              parent=protocol_id_trace,
                                              hash=m.hexdigest(),
                                              step_order=step['step_order'],
                                              user=request.user.queuedb_profile_related.delegate))
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

                    Step.objects.bulk_create(steps)
                    archive_protocol(request, protocol.id)
                    if len(predictions):
                        Prediction.objects.bulk_create(predictions)
                    return HttpResponseRedirect('/ui/query-protocol')
            except Exception as e:
                return render(request, 'ui/error.html', {'error_msg': e})
        else:
            return render(request, 'ui/error.html', {'error_msg': str(form.errors)})
    else:
        return render(request, 'ui/error.html', {'error_msg': 'Error method'})


def query_protocol_atom(is_staff, user, page):
    if is_staff:
        protocol_list = ProtocolList.objects.order_by('-id').all()
    else:
        protocol_list = ProtocolList.objects.filter(Q(user=user) | Q(user=None)).order_by('-id').all()

    paginator = Paginator(protocol_list, 25)
    return page_info(paginator, page)


@login_required
@permission_required("QueueDB.view_protocollist", raise_exception=True)
def query_protocol(request):
    protocols = query_protocol_atom(request.user.is_staff, request.user.queuedb_profile_related.delegate,
                                    request.GET.get('page'))
    if request.user.is_superuser:
        available_env = VirtualEnvironment.objects.all()
    else:
        available_env = VirtualEnvironment.objects.filter(user=request.user.queuedb_profile_related.delegate).all()
    return render(request, 'ui/list_protocol.html', {'protocol_list': protocols,
                                                     'user_envs': available_env})


@login_required
@permission_required("QueueDB.view_step", raise_exception=True)
def show_step_vc(request):
    if request.method == "GET":
        form = StepManipulateForm(request.GET)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                step = Step.objects.get(Q(user=request.user.queuedb_profile_related.delegate) | Q(user=None),
                                           id=cd["id"])
                template = loader.get_template("ui/get_version_check.html")
                context = {
                    "step_obj": step,
                }
                return success(template.render(context))
            except Step.DoesNotExist:
                return error("Cannot find the step record")
        else:
            return error(str(form.errors))
    else:
        return error('Method error.')



@login_required
@permission_required("QueueDB.view_step", raise_exception=True)
def show_step(request):
    if request.method == "POST":
        query_protocol_form = ProtocolManipulateForm(request.POST)
        if query_protocol_form.is_valid():
            cd = query_protocol_form.cleaned_data
            if request.user.is_staff:
                step_list = Step.objects.filter(parent=cd["parent"]).all().order_by("step_order")
                available_env = VirtualEnvironment.objects.all()
            else:
                step_list = Step.objects.filter(parent=cd["parent"]).all().order_by(
                    "step_order")
                available_env = VirtualEnvironment.objects.filter(
                    Q(user=request.user.queuedb_profile_related.delegate)|Q(user=None)).all()

            template = loader.get_template("ui/show_steps.html")
            context = {
                "protocol": cd["parent"],
                "step_list": step_list,
                "user_envs": available_env,
                "parent": cd["parent"],
            }
            return success(template.render(context))
        else:
            return error(str(query_protocol_form.errors))
    else:
        return error('Method error.')


@login_required
@permission_required("QueueDB.change_step", raise_exception=True)
def update_parameter(request):
    if request.method == 'GET':
        update_parameter_form = StepManipulateForm(request.GET)
        if update_parameter_form.is_valid():
            cd = update_parameter_form.cleaned_data
            step = Step.objects.get(id=cd['id'])
            if step.parent.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                step.update_parameter(unquote(cd['parameter']))
                step.save()
                archive_protocol(request, step.parent.id)
                return success('Your step has been updated.')
            else:
                return error('Your are not owner of the step.')
        else:
            return error(str(update_parameter_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_protocollist", raise_exception=True)
def update_protocol_description(request):
    if request.method == "POST":
        update_protocol_desc_form = UpdateProtocolDescForm(request.POST)
        if update_protocol_desc_form.is_valid():
            cd = update_protocol_desc_form.cleaned_data
            protocol = cd["id"]
            if protocol.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                protocol.description = cd["parameter"]
                protocol.save()
                return success("Your protocol has been updated.")
            else:
                return error("Your are not owner of the protocol.")
        else:
            return error(str(update_protocol_desc_form.errors))
    else:
        return error("Method error")


@login_required
@permission_required("QueueDB.change_step", raise_exception=True)
def update_step_environment(request):
    if request.method == "GET":
        update_env_form = StepEnvironmentManipulateForm(request.GET)
        if update_env_form.is_valid():
            cd = update_env_form.cleaned_data
            error_tag = 0
            step = cd["step"]
            if step.parent.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                step.env = cd["env"]
                step.save()
            else:
                return error("You don't have the permission to edit this step.")
            if not error_tag:
                return success("The step has been updated.")
        else:
            return error(str(update_env_form.errors))
    else:
        return error("Method error")


@login_required
@permission_required("QueueDB.change_step", raise_exception=True)
def update_step_order(request):
    if request.method == "GET":
        update_order_form = StepOrderManipulateForm(request.GET)
        if update_order_form.is_valid():
            cd = update_order_form.cleaned_data
            relations = list(filter(None, cd['step_order'].split(';')))
            error_tag = 0
            for relation in relations:
                step_id, new_order = relation.split('=')
                step = Step.objects.get(id=int(step_id), parent=cd['protocol'])
                if step.parent.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                    step.update_order(int(new_order))
                    step.save()
                else:
                    return error('Your are not owner of the step.')
            if not error_tag:
                archive_protocol(request, cd['protocol'].id)
                return success('Your step has been updated.')
        else:
            return error(str(update_order_form.errors))
    else:
        return error('Method error')


@login_required
@permission_required("QueueDB.change_step", raise_exception=True)
def update_step_prior(request):
    if request.method == "POST":
        update_prior_form = StepPriorManipulateForm(request.POST)
        if update_prior_form.is_valid():
            cd = update_prior_form.cleaned_data
            step = cd["step"]
            if step.parent.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                step.cpu_prior = cd["cpu_prior"]
                step.mem_prior = cd["mem_prior"]
                step.disk_prior = cd["disk_prior"]
                step.save()
                return success("Your step has been updated.")
            else:
                return error("Your are not owner of the step.")
        else:
            return error(str(update_prior_form.errors))
    else:
        return error("Method error")


@login_required
@permission_required("QueueDB.add_protocollist", raise_exception=True)
@permission_required("QueueDB.add_step", raise_exception=True)
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
@permission_required("QueueDB.change_step", raise_exception=True)
def update_version_check(request):
    if request.method == "POST":
        form = StepManipulateForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            step = Step.objects.get(id=cd["id"])
            if step.parent.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                step.version_check = cd["parameter"]
                step.save()
                return success("Your step has been updated.")
            else:
                return error("Your are not owner of the step.")
        else:
            return error(str(form.errors))
    else:
        return error("Method error")
