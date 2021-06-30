#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 7/24/20
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.db.models import Q
from ..tools import error, success, check_user_existence, build_json_reference
from worker.bases import get_config
from ..forms import *
from QueueDB.models import Job, ProtocolList, Step, Reference
import os
import base64
from urllib.parse import unquote


@login_required
@permission_required("QueueDB.add_reference", raise_exception=True)
def install_reference(request):
    if request.method == "POST":
        import hashlib
        from json import loads
        from ..tools import get_maintenance_protocols
        ref_info = loads(request.POST["tool"])
        if type(ref_info["software"]) == str or type(ref_info["software"]) == unicode:
            protocol_name = ref_info["how_get"] + "_" + ref_info["compression"] + "_" + ref_info["software"]
        else:
            protocol_name = ref_info["how_get"] + "_" + ref_info["compression"] + "_" + "_".join(ref_info["software"])
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
                step_order, sub_steps = model.get_sub_protocol(Step, protocol_parent, step_order)
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
                    step_order, sub_steps = model.get_sub_protocol(Step, protocol_parent, step_order)
                    for sub_step in sub_steps:
                        steps.append(sub_step)
            # post-decompression
            if type(ref_info['software']) == str or type(ref_info['software']) == unicode:
                step_order += 1
                m = hashlib.md5((ref_info['software'] + ' ' + ref_info['parameter'].strip()).encode())
                # m.update(ref_info['software'] + ' ' + ref_info['parameter'].strip())
                steps.append(Step(software=ref_info['software'],
                                  parameter=ref_info['parameter'].strip(),
                                  parent=protocol_parent,
                                  hash=m.hexdigest(),
                                  step_order=step_order,
                                  user_id=0))
            elif len(ref_info['software']) == len(ref_info['parameter']) and len(ref_info['software']) >= 1:
                for ind, software in enumerate(ref_info['software']):
                    step_order += 1
                    m = hashlib.md5((software + ' ' + ref_info['parameter'][ind].strip()).encode())
                    # m.update(software + ' ' + ref_info['parameter'][ind].strip())
                    steps.append(Step(software=software,
                                      parameter=ref_info['parameter'][ind].strip(),
                                      parent=protocol_parent,
                                      hash=m.hexdigest(),
                                      step_order=step_order,
                                      user_id=0))
            # move to user's ref folder
            steps.append(Step(software="mv",
                              parameter="{{CompileTargets}} {{UserRef}}",
                              parent=protocol_parent,
                              user_id=0,
                              hash='d885188751fc204ad7bbdf63fc6564df',
                              step_order=step_order + 1))
            Step.objects.bulk_create(steps)
        user_ref_dir = os.path.join(
            os.path.join(get_config('env', 'workspace'), str(request.user.queuedb_profile_related.delegate.id)),
            'ref')
        if not os.path.exists(user_ref_dir):
            try:
                os.makedirs(user_ref_dir)
            except:
                return error('Fail to create your reference folder')
        if "target_files" in ref_info.keys():
            mv_parameter = " ".join(ref_info["target_files"].split(";"))
        else:
            mv_parameter = "{{LastOutput}}"
        job = Job(
            protocol_id=protocol_parent.id,
            parameter='UserRef=%s;CompileTargets=%s' % (user_ref_dir, mv_parameter),
            run_dir=get_config('env', 'workspace'),
            user_id=request.user.queuedb_profile_related.delegate.id,
            input_file=ref_info["url"],
        )
        target_files = ref_info["target_files"].split(";")
        # create links to references
        ref_list = list()
        for target_file in target_files:
            ref_list.append(Reference(
                name=ref_info['name'],
                path=os.path.join(user_ref_dir, target_file),
                description=ref_info['description'],
                user_id=request.user.queuedb_profile_related.delegate.id,
            ))
        if len(ref_list) > 0:
            Reference.objects.bulk_create(ref_list)
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
def print_user_reference(request):
    result = list()
    try:
        refs = Reference.objects.filter(user_id=request.user.queuedb_profile_related.delegate)
        for ref in refs:
            result.append(ref.name)
        return build_json_reference(result)
    except:
        return build_json_reference(result)


@login_required
def send_file_as_reference(request, f):
    user_workspace = os.path.join(get_config('env', 'workspace'),
                                  str(request.user.queuedb_profile_related.delegate.id))
    file_path = os.path.join(user_workspace, base64.b64decode(f.replace('f/', '')).decode())
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
                if protocol.check_owner(request.user.queuedb_profile_related.delegate):
                    new_protocol = deepcopy(protocol)
                    new_protocol.id = None
                    new_protocol.user_id = to_user
                    new_protocol.save()
                    steps = Step.objects.filter(parent=cd['pro'])
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
