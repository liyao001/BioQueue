#!/usr/bin/env python
from __future__ import print_function
from multiprocessing import cpu_count
import baseDriver
import time
import os
import parameterParser
import django_initial

try:
    from HTMLParser import HTMLParser
except ImportError:
    from html.parser import HTMLParser

import checkPoint
from ui.models import Queue, Protocol, References, Training
import threading
import subprocess
import psutil


settings = baseDriver.get_all_config()
CPU_POOL, MEMORY_POOL, DISK_POOL, VRT_POOL = baseDriver.get_init_resource()
MAX_JOB = cpu_count()
JOB_TABLE = dict()
USER_REFERENCES = dict()
JOB_PARAMETERS = dict()
JOB_COMMAND = dict()
RUN_PARAMETERS = dict()
JOB_INPUT_FILES = dict()
LAST_OUTPUT_STRING = dict()
OUTPUTS = dict()
OUTPUT_DICT = dict()
OUTPUT_DICT_SUFFIX = dict()
NEW_FILES = dict()
LAST_OUTPUT = dict()
LAST_OUTPUT_SUFFIX = dict()
INPUT_SIZE = dict()
OUTPUT_SIZE = dict()
FOLDER_SIZE_BEFORE = dict()
CUMULATIVE_OUTPUT_SIZE = dict()
USER_MAIL_DICT = dict()
RESOURCES = dict()
LATEST_JOB_ID = 0
LATEST_JOB_STEP = 0
RUNNING_JOBS = 0
root_path = os.path.split(os.path.realpath(__file__))[0]


def get_steps(protocol_id):
    """
    Get steps of a protocol
    :param protocol_id: int, protocol id
    :return: list, list of unresolved steps
    """
    step_list = []

    steps = Protocol.objects.filter(parent=protocol_id).order_by('step_order')
    html_parser = HTMLParser()
    workspace_path = settings['env']['workspace']
    for index, step in enumerate(steps):
        # priority for self-compiled tool
        software_path = os.path.join(os.path.join(os.path.join(workspace_path, str(step.user_id)), 'bin'),
                                     str(step.software))
        if os.path.exists(software_path) and os.path.isfile(software_path):
            step.software = software_path
        step_list.append({
            'id': index,
            'parameter': html_parser.unescape(str(step.software).rstrip() + " " + str(step.parameter)),
            'specify_output': step.specify_output,
            'hash': step.hash,
        })
    return step_list


def get_user_mail(user):
    """
    Get user email address
    :param user: int, user id
    :return: string, email address, return '' when no record was found
    """
    global USER_MAIL_DICT
    if user in USER_MAIL_DICT.keys():
        return USER_MAIL_DICT[user]
    else:
        try:
            from django.contrib.auth.models import User
            user_obj = User.objects.get(id=int(user))
            USER_MAIL_DICT[user] = user_obj.email
            return user_obj.email
        except:
            return ''


def get_user_reference(user):
    """
    Get user references
    :param user: int, user id
    :return: None, the references will be stored directly into the USER_REFERENCES dictionary
    """
    references = References.objects.filter(user_id=user)
    for reference in references:
        if user not in USER_REFERENCES.keys():
            USER_REFERENCES[user] = dict()
        if reference.name in USER_REFERENCES[user]:
            continue
        else:
            USER_REFERENCES[user][reference.name] = reference.path


def create_user_folder(uf, jf):
    """
    Create user folder
    :param uf: string, path to user's folder
    :param jf: string, path to job's folder
    :return: None
    """
    try:
        if not os.path.exists(uf):
            os.mkdir(uf)
        if not os.path.exists(jf):
            os.mkdir(jf)
    except Exception as e:
        print(e)


def prepare_workspace(resume, run_folder, job_id, user_id, result=''):
    """
    Build path info for the execution of a job
    :param resume: int, if resume equals to 1, BioQueue will use the old folder instead of creating a new one
    :param run_folder: string, parent folder
    :param job_id: int, job id
    :param user_id: int, user id
    :param result: string, folder name for the job
    :return: tuple, path to user folder and job folder
    """
    if resume == -1:
        result_store = baseDriver.rand_sig() + str(job_id)
        user_folder = os.path.join(run_folder, str(user_id))
        run_folder = os.path.join(user_folder, result_store)
        create_user_folder(user_folder, run_folder)
        # baseDriver.update(settings['datasets']['job_db'], job_id, 'result', result_store)
        try:
            job_record = Queue.objects.get(id=job_id)
            job_record.set_result(result_store)
        except:
            pass
    else:
        result_store = result
        user_folder = os.path.join(run_folder, str(user_id))
        run_folder = os.path.join(user_folder, result_store)
    return user_folder, run_folder


def initialize_job_parameters(job_parameter, input_file, user, job_id):
    """
    Parse reference and job parameter (special and input files)
    :param job_parameter: list, job parameter
    :param input_file: list, input files
    :param user: int, user id
    :param job_id: int, job id
    :return: None
    """
    JOB_PARAMETERS[job_id] = parameterParser.build_special_parameter_dict(job_parameter)
    get_user_reference(user)
    if user in USER_REFERENCES.keys():
        JOB_PARAMETERS[job_id] = dict(JOB_PARAMETERS[job_id], **USER_REFERENCES[user])
    JOB_INPUT_FILES[job_id] = input_file.split(';')
    INPUT_SIZE[job_id] = 0


def get_job(max_fetch=1):
    """
    Get job information and store into JOB_TABLE
    :param max_fetch: int, the amount of records to fetch
    :return: None
    """
    job_table = dict()
    global JOB_TABLE, OUTPUT_DICT, LAST_OUTPUT, CUMULATIVE_OUTPUT_SIZE, OUTPUT_DICT_SUFFIX, LAST_OUTPUT_SUFFIX
    # fetch jobs
    jobs = Queue.objects.filter(status=0)[:max_fetch]
    for job in jobs:
        if job.id in JOB_TABLE.keys():
            continue
        else:
            user_folder, job_folder = prepare_workspace(job.resume, job.run_dir, job.id, job.user_id, job.result)
            initialize_job_parameters(job.parameter, job.input_file, job.user_id, job.id)
            JOB_TABLE[job.id] = {
                'protocol': job.protocol_id,
                'input_file': job.input_file,
                'parameter': job.parameter,
                'run_dir': job.run_dir,
                'result': job.result,
                'status': job.status,
                'user_id': job.user_id,
                'resume': job.resume,
                'steps': get_steps(job.protocol_id),
                'user_folder': user_folder,
                'job_folder': job_folder,
                'wait_for': 0,
            }
            OUTPUT_DICT[job.id] = dict()
            OUTPUT_DICT_SUFFIX[job.id] = dict()
            LAST_OUTPUT[job.id] = []
            LAST_OUTPUT_SUFFIX[job.id] = dict()
            CUMULATIVE_OUTPUT_SIZE[job.id] = 0


def get_training_items(step_hash):
    """
    Get the amount of training items
    :param step_hash: string, step hash
    :return: int, the number of training items
    """
    trainings = Training.objects.filter(step=step_hash, lock=0)
    return len(trainings)


def create_machine_learning_item(step_hash, input_size):
    """
    Create machine learning item and store it into the training table
    :param step_hash: string
    :param input_size: int
    :return: record id
    """
    training = Training(step=step_hash, input=input_size, lock=1)
    training.save()
    return training.id


def update_resource_pool(resource_dict, direction=1):
    global CPU_POOL, MEMORY_POOL, DISK_POOL, VRT_POOL
    if resource_dict['cpu'] is not None:
        CPU_POOL += direction * resource_dict['cpu']
    if resource_dict['mem'] is not None:
        MEMORY_POOL += direction * resource_dict['mem']
    if resource_dict['disk'] is not None:
        DISK_POOL += direction * resource_dict['disk']
    if resource_dict['vrt_mem'] is not None:
        VRT_POOL += direction * resource_dict['vrt_mem']

    return CPU_POOL, MEMORY_POOL, DISK_POOL, VRT_POOL


def finish_job(job_id, error=0):
    """
    Mark a job as finished and release resources it occupied
    If mail notify is switched on, it will send e-mail
    :param job_id: int, job id
    :param error: int, if error occurs, it should be 1
    :return: None
    """
    global DISK_POOL, JOB_TABLE, NEW_FILES, OUTPUTS, OUTPUT_DICT,\
        OUTPUT_SIZE, FOLDER_SIZE_BEFORE, CUMULATIVE_OUTPUT_SIZE,\
        LAST_OUTPUT_STRING, LAST_OUTPUT_SUFFIX, OUTPUT_DICT_SUFFIX
    if job_id in JOB_TABLE.keys():
        if error == 1:
            if settings['mail']['notify'] == 'on':
                try:
                    from notify import MailNotify
                    mail = MailNotify(JOB_TABLE[job_id]['user_id'], 2, job_id, JOB_TABLE[job_id]['protocol'],
                                      JOB_TABLE[job_id]['input_file'], JOB_TABLE[job_id]['parameter'])
                    mail.send_mail(mail.get_user_mail_address(JOB_TABLE[job_id]['user_id']))
                except Exception as e:
                    print(e)
        else:
            try:
                job = Queue.objects.get(id=job_id)
                job.status = -1
                job.save()
            except:
                pass
            baseDriver.del_output_dict(job_id)
            if settings['mail']['notify'] == 'on':
                try:
                    from notify import MailNotify
                    mail = MailNotify(JOB_TABLE[job_id]['user_id'], 1, job_id, JOB_TABLE[job_id]['protocol'],
                                      JOB_TABLE[job_id]['input_file'], JOB_TABLE[job_id]['parameter'])
                    mail.send_mail(mail.get_user_mail_address(JOB_TABLE[job_id]['user_id']))
                except Exception as e:
                    print(e)

        if job_id in JOB_TABLE.keys():
            resume = JOB_TABLE[job_id]['resume']
            res_key = str(job_id) + '_' + str(resume + 1)
            if res_key in RESOURCES.keys():
                RESOURCES.pop(res_key)
        DISK_POOL += CUMULATIVE_OUTPUT_SIZE[job_id] - baseDriver.get_folder_size(JOB_TABLE[job_id]['job_folder'])
        JOB_TABLE.pop(job_id)
        if job_id in OUTPUTS.keys():
            OUTPUTS.pop(job_id)
        if job_id in OUTPUT_DICT.keys():
            OUTPUT_DICT.pop(job_id)
        if job_id in LAST_OUTPUT.keys():
            LAST_OUTPUT.pop(job_id)
        if job_id in LAST_OUTPUT_STRING.keys():
            LAST_OUTPUT_STRING.pop(job_id)
        if job_id in CUMULATIVE_OUTPUT_SIZE.keys():
            CUMULATIVE_OUTPUT_SIZE.pop(job_id)
        if job_id in LAST_OUTPUT_SUFFIX.keys():
            LAST_OUTPUT_SUFFIX.pop(job_id)
        if job_id in OUTPUT_DICT_SUFFIX.keys():
            OUTPUT_DICT_SUFFIX.pop(job_id)


def run_prepare(job_id, job, no_new_learn=0):
    """
    Parse step's parameter and predict the resources needed by the step
    :param job_id: int, jod id
    :param job: dict, job dict
    :param no_new_learn: int, 1 means refusing creating new training item
    :return:
    """
    global LAST_OUTPUT_STRING, OUTPUTS, OUTPUT_DICT, OUTPUT_DICT_SUFFIX, NEW_FILES, LAST_OUTPUT, LAST_OUTPUT_STRING
    learning = 0
    outside_size = 0

    if job['status'] == -1 and job['resume'] != -1:
        # skip and resume
        tmp_dict = baseDriver.load_output_dict(job_id)
        if 'LAST_OUTPUT_STRING' in tmp_dict.keys():
            LAST_OUTPUT_STRING[job_id] = tmp_dict['LAST_OUTPUT_STRING']
        if 'OUTPUTS' in tmp_dict.keys():
            OUTPUTS[job_id] = tmp_dict['OUTPUTS']
        if 'OUTPUT_DICT' in tmp_dict.keys():
            OUTPUT_DICT[job_id] = tmp_dict['OUTPUT_DICT']
        if 'OUTPUT_DICT_SUFFIX' in tmp_dict.keys():
            OUTPUT_DICT_SUFFIX[job_id] = tmp_dict['OUTPUT_DICT_SUFFIX']
        if 'NEW_FILES' in tmp_dict.keys():
            NEW_FILES[job_id] = tmp_dict['NEW_FILES']
        if 'LAST_OUTPUT' in tmp_dict.keys():
            LAST_OUTPUT[job_id] = tmp_dict['LAST_OUTPUT']
        if 'LAST_OUTPUT_SUFFIX' in tmp_dict.keys():
            LAST_OUTPUT_SUFFIX[job_id] = tmp_dict['LAST_OUTPUT_SUFFIX']

    if (job['resume'] + 1) == len(job['steps']):
        return None
    elif job['status'] > 0:
        return 'running'
    else:
        step = job['steps'][job['resume'] + 1]['parameter']

    step = step.replace('{Job}', str(job_id))

    if job_id in LAST_OUTPUT_STRING.keys():
        step = step.replace('{LastOutput}', LAST_OUTPUT_STRING[job_id])
    if job_id in OUTPUTS.keys():
        step = step.replace('{AllOutputBefore}', ' '.join(OUTPUTS[job_id]))
    if job_id in NEW_FILES.keys():
        step = parameterParser.last_output_map(step, NEW_FILES[job_id])
    if job_id in JOB_PARAMETERS.keys():
        step = parameterParser.special_parameter_map(step, JOB_PARAMETERS[job_id])
    if job_id in OUTPUT_DICT.keys():
        step = parameterParser.output_file_map(step, OUTPUT_DICT[job_id])
    if job_id in JOB_INPUT_FILES.keys():
        step, outside_size = parameterParser.input_file_map(step, JOB_INPUT_FILES[job_id], job['user_folder'])
    if job_id in LAST_OUTPUT_SUFFIX.keys() and job_id in OUTPUT_DICT_SUFFIX.keys():
        step = parameterParser.suffix_map(step, OUTPUT_DICT_SUFFIX[job_id], LAST_OUTPUT_SUFFIX[job_id])
    step = parameterParser.history_map(step, job['user_id'], job['user_folder'], Queue)

    step, outside_size_upload = parameterParser.upload_file_map(step, job['user_folder'])
    outside_size += outside_size_upload
    step = step.replace('{Workspace}', job['job_folder'])
    user_bin_dir = os.path.join(os.path.join(settings['env']['workspace'], job['user_id'], 'bin'))
    if not os.path.exists(user_bin_dir):
        try:
            os.makedirs(user_bin_dir)
        except:
            pass
    step = step.replace('{UserBin}', user_bin_dir)
    step = step.replace('{ThreadN}', str(settings['env']['cpu']))
    JOB_COMMAND[job_id] = parameterParser.parameter_string_to_list(step)
    LAST_OUTPUT[job_id] = baseDriver.get_folder_content(job['job_folder'])
    training_num = get_training_items(job['steps'][job['resume'] + 1]['hash'])
    if training_num < 10:
        learning = 1

    if INPUT_SIZE[job_id] == 0:
        INPUT_SIZE[job_id] = baseDriver.get_folder_size(job['job_folder'])
    else:
        if job_id in OUTPUT_SIZE.keys():
            INPUT_SIZE[job_id] = OUTPUT_SIZE[job_id]
        else:
            INPUT_SIZE[job_id] = 0
    FOLDER_SIZE_BEFORE[job_id] = baseDriver.get_folder_size(job['job_folder'])
    INPUT_SIZE[job_id] += outside_size

    resource_needed = checkPoint.predict_resource_needed(job['steps'][job['resume'] + 1]['hash'],
                                                         INPUT_SIZE[job_id],
                                                         training_num)
    if resource_needed['cpu'] > int(settings['env']['cpu']) * 100:
        resource_needed['cpu'] = int(settings['env']['cpu']) * 95

    # if resource_needed['mem'] >
    if learning == 1 and no_new_learn == 0:
        trace_id = create_machine_learning_item(job['steps'][job['resume'] + 1]['hash'], INPUT_SIZE[job_id])
        resource_needed['trace'] = trace_id

    return resource_needed


def forecast_step(job_id, step_order, resources):
    """
    Before the running of a step
    :param job_id: int, job id
    :param step_order: int, step order
    :param resources: dictionary, resources required by the step
    :return: If system resources is not enough for the step, it will return False, otherwise, it returns True
    """
    global JOB_TABLE
    rollback = 0

    if settings['cluster']['type'] == '':
        # for clusters
        new_cpu, new_mem, new_disk, new_vrt_mem = update_resource_pool(resources, -1)

        if new_cpu < 0 or new_mem < 0 or new_disk < 0 or new_vrt_mem < 0:
            rollback = 1

    if not rollback:
        try:
            job = Queue.objects.get(id=job_id)
            job.set_status(step_order + 1)
        except:
            pass
        JOB_TABLE[job_id]['status'] = step_order + 1
        return True
    else:
        update_resource_pool(resources)
        return False


def build_suffix_dict(output_files):
    """
    Build suffix dictionary for output file
    :param output_files: list, output files
    :return: dict, suffix dictionary
    """
    suffix_dict = dict()
    for output_file in output_files:
        _, suffix = os.path.splitext(output_file)
        suffix = suffix.replace('.', '')
        if suffix in suffix_dict.keys():
            suffix_dict[suffix].append(output_file)
        else:
            suffix_dict[suffix] = [output_file]
    return suffix_dict


def finish_step(job_id, step_order, resources):
    """
    Mark a step as finished
    :param job_id: int, job id
    :param step_order: int, step order
    :param resources: dictionary, resources required by the step
    :return: None
    """
    global JOB_TABLE, NEW_FILES, OUTPUTS, OUTPUT_DICT, OUTPUT_SIZE, FOLDER_SIZE_BEFORE,\
        CUMULATIVE_OUTPUT_SIZE, LAST_OUTPUT_STRING
    try:
        job = Queue.objects.get(id=job_id)
        job.resume = step_order
        job.status = -2
        job.save()
        JOB_TABLE[job_id]['status'] = -2
        JOB_TABLE[job_id]['resume'] = step_order
        this_output = baseDriver.get_folder_content(JOB_TABLE[job_id]['job_folder'])
        NEW_FILES[job_id] = sorted(list(set(this_output).difference(set(LAST_OUTPUT[job_id]))))
        NEW_FILES[job_id] = [os.path.join(JOB_TABLE[job_id]['job_folder'], file_name)
                             for file_name in NEW_FILES[job_id]]
    except Exception as e:
        print(e)

    if job_id in OUTPUTS.keys():
        OUTPUTS[job_id].extend(NEW_FILES[job_id])
    else:
        OUTPUTS[job_id] = NEW_FILES[job_id]

    suffix_dict = build_suffix_dict(NEW_FILES[job_id])

    if job_id in OUTPUT_DICT.keys():
        OUTPUT_DICT[job_id][step_order + 1] = NEW_FILES[job_id]
    else:
        OUTPUT_DICT[job_id] = {step_order + 1: NEW_FILES[job_id]}

    if job_id in OUTPUT_DICT_SUFFIX.keys():
        OUTPUT_DICT_SUFFIX[job_id][step_order+1] = suffix_dict
    else:
        OUTPUT_DICT_SUFFIX[job_id] = {step_order + 1: suffix_dict}

    LAST_OUTPUT_SUFFIX[job_id] = suffix_dict
    LAST_OUTPUT_STRING[job_id] = ' '.join(NEW_FILES[job_id])
    OUTPUT_SIZE[job_id] = baseDriver.get_folder_size(JOB_TABLE[job_id]['job_folder']) - FOLDER_SIZE_BEFORE[job_id]
    CUMULATIVE_OUTPUT_SIZE[job_id] += OUTPUT_SIZE[job_id]

    if 'trace' in resources.keys():
        training_item = Training.objects.get(id=resources['trace'])
        if training_item.cpu != '-' and training_item.mem != '-' \
                and training_item.cpu != '' and training_item.mem != '':
            training_item.output = OUTPUT_SIZE[job_id]
            training_item.lock = 0
            training_item.save()

    if settings['cluster']['type'] == '':
        update_resource_pool(resources)


def error_job(job_id, resources):
    """
    Error occurs
    :param job_id: int, job id
    :param resources: dict, job resources
    :return: None
    """
    try:
        job = Queue.objects.get(id=job_id)
        job.status = -3
        job.ter = 0
        job.save()
    except:
        pass

    file_map = dict()
    if job_id in OUTPUT_DICT.keys():
        file_map['OUTPUT_DICT'] = OUTPUT_DICT[job_id]
    if job_id in LAST_OUTPUT_STRING.keys():
        file_map['LAST_OUTPUT_STRING'] = LAST_OUTPUT_STRING[job_id]
    if job_id in OUTPUT_DICT_SUFFIX.keys():
        file_map['OUTPUT_DICT_SUFFIX'] = OUTPUT_DICT_SUFFIX[job_id]
    if job_id in OUTPUTS.keys():
        file_map['OUTPUTS'] = OUTPUTS[job_id]
    if job_id in NEW_FILES.keys():
        file_map['NEW_FILES'] = NEW_FILES[job_id]
    if job_id in LAST_OUTPUT.keys():
        file_map['LAST_OUTPUT'] = LAST_OUTPUT[job_id]
    if job_id in LAST_OUTPUT_SUFFIX.keys():
        file_map['LAST_OUTPUT_SUFFIX'] = LAST_OUTPUT_SUFFIX[job_id]

    baseDriver.save_output_dict(file_map, job_id)

    update_resource_pool(resources)

    if 'trace' in resources.keys():
        try:
            training = Training.objects.get(id=resources['trace'])
            training.delete()
        except:
            pass

    finish_job(job_id, 1)


def kill_proc(proc):
    """
    Kill a process and its children processes
    :param proc: Process class defined in psutil
    :return: None
    """
    try:
        children = proc.children()
        for child in children:
            try:
                child.terminate()
            except:
                pass
        gone, still_alive = psutil.wait_procs(children, timeout=3)
        for p in still_alive:
            p.kill()
        proc.kill()
    except:
        pass


def bytes_to_readable(bytes_value):
    """
    Convert bytes to a readable form
    :param bytes_value: int, bytes
    :return: string, readable value, like 1GB
    """
    from math import ceil
    if bytes_value > 1073741824:
        # 1073741824 = 1024 * 1024 * 1024
        # bytes to gigabytes
        readable_value = str(int(ceil(bytes_value * 1.1 / 1073741824))) + 'GB'
    elif bytes_value > 1048576:
        # 1048576 = 1024 * 1024
        # bytes to megabytes
        readable_value = str(int(ceil(bytes_value * 1.1 / 1048576))) + 'MB'
    else:
        # bytes to kilobytes
        readable_value = str(int(ceil(bytes_value * 1.1 / 1024))) + 'KB'
    return readable_value


def run_step(job_desc, resources):
    """
    Run step (parallel to main thread)
    :param job_desc: string, jod id + "_" + step order
    :param resources: dictionary, resources required by the step
    :return: None
    """
    global LATEST_JOB_ID, LATEST_JOB_STEP, CPU_POOL, MEMORY_POOL, DISK_POOL, RUNNING_JOBS
    items = job_desc.split('_')
    job_id = int(items[0])
    step_order = int(items[1])
    user_id = JOB_TABLE[job_id]['user_id']
    recheck = forecast_step(job_id, step_order, resources)

    log_file = os.path.join(settings["env"]["log"], str(job_id))

    if recheck is not True:
        return
    if 'feedback' in settings['env'].keys() and settings['env']['feedback'] == 'yes':
        try:
            from feedback import feedback
            feedback(JOB_COMMAND[job_id][0],
                     ' '.join(JOB_COMMAND[job_id][1:]), get_user_mail(JOB_TABLE[job_id]['user_id']))
        except:
            pass

    if settings['cluster']['type']:
        # for cluster
        import clusterSupport
        if resources['cpu'] is None:
            allocate_cpu = settings['cluster']['cpu']
        else:
            from math import ceil
            predict_cpu = int(ceil(round(resources['cpu']) / 100))
            if predict_cpu > settings['cluster']['cpu'] or predict_cpu == 0:
                allocate_cpu = settings['cluster']['cpu']
            else:
                allocate_cpu = predict_cpu
        if resources['mem'] is None:
            allocate_mem = settings['cluster']['mem']
        else:
            allocate_mem = bytes_to_readable(resources['mem'])
        if resources['vrt_mem'] is None:
            allocate_vrt = settings['cluster']['vrt']
        else:
            allocate_vrt = bytes_to_readable(resources['vrt_mem'])
        # baseDriver.update(settings['datasets']['job_db'], job_id, 'status', step_order + 1)
        try:
            job_record = Queue.objects.get(id=job_id)
            job_record.set_status(step_order+1)
        except:
            pass

        if 'trace' in resources.keys():
            # learn
            return_code = clusterSupport.main(settings['cluster']['type'], ' '.join(JOB_COMMAND[job_id]),
                                              job_id, step_order, allocate_cpu, allocate_mem, allocate_vrt,
                                              settings['cluster']['queue'], JOB_TABLE[job_id]['job_folder'],
                                              log_file, settings['cluster']['walltime'], 1, resources['trace'])
        else:
            return_code = clusterSupport.main(settings['cluster']['type'], ' '.join(JOB_COMMAND[job_id]),
                                              job_id, step_order, allocate_cpu, allocate_mem, allocate_vrt,
                                              settings['cluster']['queue'], JOB_TABLE[job_id]['job_folder'],
                                              log_file, settings['cluster']['walltime'])

        if return_code != 0:
            try:
                from feedback import feedback_error, get_error_log
                feedback_error(JOB_COMMAND[job_id][0],
                               ' '.join(JOB_COMMAND[job_id][1:]),
                               get_error_log(log_file), get_user_mail(user_id))
            except:
                pass
            error_job(job_id, resources)
        else:
            # RUNNING_JOBS -= 1
            finish_step(job_id, step_order, resources)
    else:
        # for local environment or cloud
        print("Now run %s" % job_desc)
        print(CPU_POOL, MEMORY_POOL, DISK_POOL)
        try:
            log_file_handler = open(log_file, "a")
            RUNNING_JOBS += 1
            true_shell = 0
            redirect_tags = ('>', '<', '|', ';')

            for rt in redirect_tags:
                if rt in JOB_COMMAND[job_id]:
                    true_shell = 1
                    break

            if true_shell:
                step_process = subprocess.Popen(' '.join(JOB_COMMAND[job_id]), shell=True,
                                                cwd=JOB_TABLE[job_id]['job_folder'])
            else:
                step_process = subprocess.Popen(JOB_COMMAND[job_id], shell=False, stdout=log_file_handler,
                                                stderr=log_file_handler, cwd=JOB_TABLE[job_id]['job_folder'])
            # step_process = subprocess.Popen(JOB_COMMAND[job_id], shell=False, stdout=log_file_handler,
            #                                stderr=log_file_handler, cwd=JOB_TABLE[job_id]['job_folder'])
            process_id = step_process.pid
            if 'trace' in resources.keys():
                learn_process = subprocess.Popen(["python", os.path.join(root_path, 'mlCollector.py'),
                                                  "-p", str(step_process.pid), "-n",
                                                  str(JOB_TABLE[job_id]['steps'][step_order]['hash']),
                                                  "-j", str(resources['trace'])], shell=False, stdout=None,
                                                 stderr=subprocess.STDOUT)
            while step_process.poll() is None:
                if process_id in psutil.pids():
                    proc_info = psutil.Process(process_id)
                    if proc_info.is_running():
                        job = Queue.objects.get(id=job_id)
                        if job.ter:
                            job.status = -3
                            job.ter = 0
                            job.save()
                            # proc_info.kill()
                            kill_proc(proc_info)
                            # step_process.kill()
                            error_job(job_id, resources)
                            RUNNING_JOBS -= 1

                            return None

                time.sleep(30)
            log_file_handler.close()
            print("Now job %s finished." % job_desc)
            # finish_step(job_id, step_order, resources)
            if step_process.returncode != 0:
                RUNNING_JOBS -= 1
                error_job(job_id, resources)
            else:
                RUNNING_JOBS -= 1
                finish_step(job_id, step_order, resources)
            JOB_TABLE[job_id]['resume'] = step_order
            if job_id > LATEST_JOB_ID and (step_order + 1) > LATEST_JOB_STEP:
                LATEST_JOB_ID = job_id
                LATEST_JOB_STEP = step_order
        except Exception as e:
            print(e)
            try:
                from feedback import feedback_error, get_error_log
                feedback_error(JOB_COMMAND[job_id][0],
                               ' '.join(JOB_COMMAND[job_id][1:]),
                               get_error_log(log_file), get_user_mail(user_id))
            except:
                pass
            RUNNING_JOBS -= 1
            error_job(job_id, resources)


def set_checkpoint_info(job_id, cause):
    """
    Interact with frontend for checkpoint
    :param job_id: int, job id
    :param cause: int, cause for the suspension
    :return: None
    """
    global JOB_TABLE
    try:
        if JOB_TABLE[job_id]['wait_for'] != cause:
            JOB_TABLE[job_id]['wait_for'] = cause
            job = Queue.objects.get(id=job_id)
            job.wait_for = cause
            job.status = -2
            job.save()
    except:
        pass


def reset_status():
    """
    Reset dead jobs
    :return: 0/1
    """
    try:
        Queue.objects.filter(status__gt=0).update(status=-3)
        return 1
    except:
        return 0


def main():
    global LATEST_JOB_ID, LATEST_JOB_STEP, RESOURCES
    reset_status()
    while True:
        try:
            cpu_indeed = baseDriver.get_cpu_available()
            mem_indeed, vrt_indeed = baseDriver.get_memo_usage_available()
            disk_indeed = baseDriver.get_disk_free(settings['env']['workspace'])
            get_job(MAX_JOB - len(JOB_TABLE))

            sorted_job_info = sorted(JOB_TABLE.keys())
            for job_id in sorted_job_info:
                previous_step = str(job_id) + '_' + str(JOB_TABLE[job_id]['resume'])
                now_step = str(job_id) + '_' + str(JOB_TABLE[job_id]['resume'] + 1)

                if previous_step in RESOURCES.keys():
                    RESOURCES.pop(previous_step)

                if now_step in RESOURCES.keys():
                    if RESOURCES[now_step]['cpu'] is None \
                            and RESOURCES[now_step]['mem'] is None \
                            and RESOURCES[now_step]['disk'] is None:
                        resource = run_prepare(job_id, JOB_TABLE[job_id], 1)
                        if 'trace' in RESOURCES[now_step].keys() and resource != 'running':
                            resource['trace'] = RESOURCES[now_step]['trace']
                    else:
                        continue
                else:
                    resource = run_prepare(job_id, JOB_TABLE[job_id])
                if resource is None:
                    finish_job(job_id)
                    continue
                elif resource == 'running':
                    continue
                else:
                    RESOURCES[now_step] = resource

            biggest_cpu = None
            biggest_mem = None
            biggest_id = None
            biggest_vrt_mem = None

            sorted_resources_info = sorted(RESOURCES.keys())
            if settings['cluster']['type']:
                # for cluster
                # switch off greedy algorithm
                for index, job_desc in enumerate(sorted_resources_info):
                    items = job_desc.split('_')
                    job_id = int(items[0])
                    step_order = int(items[1])

                    if job_id not in JOB_TABLE.keys():
                        continue
                    if JOB_TABLE[job_id]['status'] > 0:
                        continue

                    if RESOURCES[job_desc]['cpu'] is None \
                            and RESOURCES[job_desc]['mem'] is None \
                            and RESOURCES[job_desc]['disk'] is None:
                        if RUNNING_JOBS > 0:
                            set_checkpoint_info(job_id, 4)
                        else:
                            new_thread = threading.Thread(target=run_step, args=(job_desc, RESOURCES[job_desc]))
                            new_thread.setDaemon(True)
                            new_thread.start()
                        break
                    else:
                        new_thread = threading.Thread(target=run_step, args=(job_desc, RESOURCES[job_desc]))
                        new_thread.setDaemon(True)
                        new_thread.start()
            else:
                # local / cloud
                # greedy algorithm
                for index, job_desc in enumerate(sorted_resources_info):
                    items = job_desc.split('_')
                    job_id = int(items[0])
                    step_order = int(items[1])

                    if job_id not in JOB_TABLE.keys():
                        continue
                    if JOB_TABLE[job_id]['status'] > 0:
                        continue

                    if RESOURCES[job_desc]['cpu'] is None \
                            and RESOURCES[job_desc]['mem'] is None \
                            and RESOURCES[job_desc]['disk'] is None:
                        if RUNNING_JOBS > 0:
                            set_checkpoint_info(job_id, 4)
                        else:
                            new_thread = threading.Thread(target=run_step, args=(job_desc, RESOURCES[job_desc]))
                            new_thread.setDaemon(True)
                            new_thread.start()
                        break
                    else:
                        if RESOURCES[job_desc]['cpu'] > cpu_indeed or RESOURCES[job_desc]['cpu'] > CPU_POOL:
                            set_checkpoint_info(job_id, 3)
                        elif RESOURCES[job_desc]['mem'] > mem_indeed or RESOURCES[job_desc]['mem'] > MEMORY_POOL:
                            set_checkpoint_info(job_id, 2)
                        elif RESOURCES[job_desc]['disk'] > disk_indeed or RESOURCES[job_desc]['disk'] > DISK_POOL:
                            set_checkpoint_info(job_id, 1)
                        elif RESOURCES[job_desc]['vrt_mem'] > vrt_indeed or RESOURCES[job_desc]['vrt_mem'] > VRT_POOL:
                            set_checkpoint_info(job_id, 6)
                        else:
                            if biggest_cpu is None:
                                biggest_cpu = RESOURCES[job_desc]['cpu']
                            if biggest_mem is None:
                                biggest_mem = RESOURCES[job_desc]['mem']
                            if biggest_id is None:
                                biggest_id = job_desc
                            if biggest_vrt_mem is None:
                                biggest_vrt_mem = RESOURCES[job_desc]['vrt_mem']

                            if biggest_cpu < RESOURCES[job_desc]['cpu']:
                                biggest_cpu = RESOURCES[job_desc]['cpu']
                                biggest_mem = RESOURCES[job_desc]['mem']
                                biggest_vrt_mem = RESOURCES[job_desc]['vrt_mem']
                                biggest_id = job_desc
                if biggest_id is not None:
                    new_thread = threading.Thread(target=run_step, args=(biggest_id, RESOURCES[biggest_id]))
                    new_thread.setDaemon(True)
                    new_thread.start()
            time.sleep(5)
        except Exception as e:
            print(e)


if __name__ == '__main__':
    main()
