from django.http import JsonResponse, StreamingHttpResponse
from worker.baseDriver import get_config, rand_sig, get_user_folder_size
import os


def success(message, jump_url='.', msg_title="success", status=1, wait_second=1):
    json_data = dict()
    json_data['msg_title'] = msg_title
    json_data['info'] = message
    json_data['url'] = jump_url
    json_data['status'] = status
    json_data['wait_second'] = wait_second
    return JsonResponse(json_data)


def error(message, jump_url='.', msg_title="error", status=0, wait_second=3):
    json_data = dict()
    json_data['msg_title'] = msg_title
    json_data['info'] = str(message)
    json_data['url'] = jump_url
    json_data['status'] = status
    json_data['wait_second'] = wait_second
    return JsonResponse(json_data)


def build_json_protocol(protocol):
    import json
    """
    response = StreamingHttpResponse(json.dumps(protocol))
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = 'attachment;filename="{0}"'.format(protocol['name']+'.txt')
    return response
    """
    return json.dumps(protocol)


def build_json_reference(ref):
    result = list()
    for value in ref:
        result.append('{'+value+'}')
    return JsonResponse(','.join(result), safe=False)


def delete_file(file_path):
    import os
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return success('Deleted')
        else:
            return error('File can not be found.')
    except Exception as e:
        return error(e)


def check_user_existence(username):
    from django.contrib.auth.models import User
    try:
        u = User.objects.get(username=username)
        return u.id
    except Exception as e:
        return 0


def handle_uploaded_file(f):
    import os
    file_name = os.path.join(get_config('env', 'batch_job'), rand_sig()+'.txt')
    with open(file_name, 'wb+') as destination:
        for chunk in f.chunks():
            destination.write(chunk)
    return file_name


def check_disk_quota_lock(user):
    disk_limit = get_config('env', 'disk_quota')
    if disk_limit:
        if get_user_folder_size(user) < int(disk_limit):
            return 1
        else:
            return 0
    else:
        return 1


def get_disk_quota_info(user):
    try:
        disk_pool = int(get_config('env', 'disk_quota'))
        disk_used = get_user_folder_size(user)
        disk_perc = int(round(disk_used / disk_pool * 100))
    except:
        disk_pool = disk_used = disk_perc = 0
    return disk_pool, disk_used, disk_perc


def os_to_int():
    import platform
    if platform.system() == 'Linux':
        return 1
    elif platform.system() == 'Darwin':
        return 3
    else:
        return 2


def get_maintenance_protocols():
    """
    Get maintenance protocols
    :return: list, module names
    """
    protocols = []
    protocols_path = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'maintenance_protocols')
    for model_name in os.listdir(protocols_path):
        if not model_name.endswith('.py') or model_name.startswith('_') or model_name.startswith('maintenance'):
            continue
        protocols.append(model_name.replace('.py', ''))
    return protocols