from django.http import JsonResponse


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


def delete_file(file_path):
    import os
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return success('Deleted')
        else:
            return error('File can not be found.')
    except Exception, e:
        return error(e)


def check_user_existence(username):
    from django.contrib.auth.models import User
    try:
        u = User.objects.get(username=username)
        return u.id
    except Exception, e:
        return 0
