#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 6/23/20
import argparse
import os
import sys
import psutil
import django_initial
from enum import IntEnum
import threading
import time
import bases
import subprocess
import logging
import numpy as np
from bases import *
from copy import copy
from _step import _Step
from django.db.models import Q
from QueueDB.models import Job, Step, Reference, Training, _JS_WAITING, _JS_RESOURCELOCK, _JS_RUNNING, _JS_FINISHED, _JS_WRONG

DEFAULT_PREFIX = str(os.getpid())
logging.basicConfig(format='%(name)s - %(asctime)s - %(levelname)s: %(message)s',
                    datefmt='%d-%b-%y %H:%M:%S',
                    level=logging.INFO,
                    handlers=[
                        logging.FileHandler(os.path.join(os.getcwd(), '%s.log' % DEFAULT_PREFIX)),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger("BioQueue")
root_path = os.path.split(os.path.realpath(__file__))[0]


class Protocol(object):
    def __init__(self, poj, settings):
        super(Protocol, self).__init__()
        # super(Protocol, self).__init__(poj, settings)
        self._ver = poj.ver
        self.raw_steps = Step.objects.filter(parent=poj).order_by("step_order")
        self._steps = []
        self._settings = settings

    @property
    def ver(self):
        return self._ver

    def customize_steps_by_user_dir(self, workspace_path):
        step_list = []
        for index, step in enumerate(self.raw_steps):
            # priority for self-compiled tool
            sp = step.software

            if workspace_path is not None and os.path.exists(workspace_path):
                if step.user is not None:
                    software_path = os.path.join(os.path.join(os.path.join(workspace_path, str(step.user.id)), "bin"),
                                                 str(step.software))
                    if os.path.exists(software_path) and os.path.isfile(software_path):
                        sp = software_path

            step_list.append(_Step(software=sp.rstrip(),
                                   parameter=str(step.parameter),
                                   specify_output=step.specify_output,
                                   md5_hex=step.hash,
                                   env=step.env,
                                   force_local=step.force_local,
                                   settings=self._settings))
        return step_list


class Task(object):
    def __init__(self, job_obj, protocol, settings):
        """

        Parameters
        ----------
        job_obj :
        protocol :
        settings :

        """
        self._db_obj = job_obj
        self._job_id = job_obj.id
        self._job_name = job_obj.job_name
        self._job_input = job_obj.input_file
        self._user = job_obj.user
        self._status = job_obj.status
        self._protocol = copy(protocol)
        self._work_dir = job_obj.run_dir

        self.prev_step = None
        self.current_step = None

        self._parameter = job_obj.parameter

        self._result = job_obj.result
        self._resume = job_obj.resume
        self._wait_for = job_obj.wait_for

        # for translating protocol
        self._steps = self._protocol.customize_steps_by_user_dir(workspace_path=self._work_dir)
        self._job_parameters = None
        self._job_input_files = self._job_input.split(";")
        self._OUTPUTS = []
        self._NEW_FILES = []
        self._OUTPUT_DICT = dict()
        self._OUTPUT_DICT_SUFFIX = dict()
        self._LAST_OUTPUT = []
        self._LAST_OUTPUT_STRING = ""
        self._LAST_OUTPUT_SUFFIX = dict()
        self._STEP_DEPENDENCIES = set()
        self._lock = threading.Lock()

        # - if user's trying to resume a job, then load previous outputs for translating job's parameters
        if self._status == -1 and self._resume != 0:
            # skip and resume
            tmp_dict = bases.load_output_dict(self._job_id)
            if "LAST_OUTPUT_STRING" in tmp_dict:
                self._LAST_OUTPUT_STRING = tmp_dict["LAST_OUTPUT_STRING"]
            if "OUTPUTS" in tmp_dict:
                self._OUTPUTS = tmp_dict["OUTPUTS"]
            if "OUTPUT_DICT" in tmp_dict:
                self._OUTPUT_DICT = tmp_dict["OUTPUT_DICT"]
            if "OUTPUT_DICT_SUFFIX" in tmp_dict:
                self._OUTPUT_DICT_SUFFIX = tmp_dict["OUTPUT_DICT_SUFFIX"]
            if "NEW_FILES" in tmp_dict:
                self._NEW_FILES = tmp_dict["NEW_FILES"]
            if "LAST_OUTPUT" in tmp_dict:
                self._LAST_OUTPUT = tmp_dict["LAST_OUTPUT"]
            if "LAST_OUTPUT_SUFFIX" in tmp_dict:
                self._LAST_OUTPUT_SUFFIX = tmp_dict["LAST_OUTPUT_SUFFIX"]

        # for predicting resources
        self._input_size = 0
        self._output_size = 0
        self._folder_size_before = 0
        self._cumulative_output_size = 0

        self._user_folder = ""
        self._run_folder = ""
        self._result_store = ""

        self._settings = settings

    def __str__(self):
        return "{job_name} ({job_id})".format(job_name=self.job_name, job_id=self.job_id)

    def __repr__(self):
        return self.__str__()

    @property
    def db_obj(self):
        return self._db_obj

    @property
    def newfiles(self):
        return self._NEW_FILES

    @newfiles.setter
    def newfiles(self, value):
        self._NEW_FILES = value

    @property
    def outputs(self):
        """

        Returns
        -------
        self._OUTPUTS : list

        """
        return self._OUTPUTS

    @property
    def output_dict(self):
        return self._OUTPUT_DICT

    @property
    def output_dict_suffix(self):
        return self._OUTPUT_DICT_SUFFIX

    @property
    def last_output(self):
        return self._LAST_OUTPUT

    @property
    def last_output_string(self):
        return self._LAST_OUTPUT_STRING

    @last_output_string.setter
    def last_output_string(self, value):
        self._LAST_OUTPUT_STRING = value

    @property
    def last_output_suffix(self):
        return self._LAST_OUTPUT_SUFFIX

    @last_output_suffix.setter
    def last_output_suffix(self, value):
        self._LAST_OUTPUT_SUFFIX = value

    @property
    def input_size(self):
        return self._input_size

    @input_size.setter
    def input_size(self, value):
        self._input_size = int(value)

    @property
    def output_size(self):
        return self._output_size

    @output_size.setter
    def output_size(self, value):
        self._output_size = int(value)

    @property
    def job_input_files(self):
        return self._job_input_files

    @property
    def user_folder(self):
        return self._user_folder

    @property
    def run_folder(self):
        return self._run_folder

    @property
    def job_id(self):
        return self._job_id

    @property
    def job_name(self):
        return self._job_name

    @property
    def job_input(self):
        return self._job_input

    @property
    def job_user(self):
        return self._user

    @property
    def job_protocol(self):
        return self._protocol

    @property
    def job_protocol_ver(self):
        return self._protocol.ver

    @property
    def resume(self):
        return self._resume

    @resume.setter
    def resume(self, value):
        if value <= len(self.steps):
            self._resume = value

    @property
    def status(self):
        return self._status

    @property
    def steps(self):
        return self._steps

    @property
    def user_options(self):
        return self._job_parameters

    @property
    def work_dir(self):
        return self._work_dir

    @property
    def file_map(self):
        return {
            "LAST_OUTPUT_STRING": self._LAST_OUTPUT_STRING,
            "OUTPUTS": self._OUTPUTS,
            "OUTPUT_DICT": self._OUTPUT_DICT,
            "OUTPUT_DICT_SUFFIX": self._OUTPUT_DICT_SUFFIX,
            "NEW_FILES": self._NEW_FILES,
            "LAST_OUTPUT": self._LAST_OUTPUT,
            "LAST_OUTPUT_SUFFIX": self._LAST_OUTPUT_SUFFIX
        }

    def get_prev_step(self):
        if self.resume - 1 > 0:
            return self._steps[self.resume - 1]
        else:
            return self.steps[0]

    def get_current_step(self):
        with self._lock:
            if self.resume < len(self.steps):
                step = self.steps[self.resume]
                if step.translated_command == "":
                    step.translate_step_to_runnable(job=self)

                if (step.resources is None or step.resources["learn"] == 1) and not step.is_running:
                    # no_new_learn
                    step.resources = step.predict_resources_needed(job=self)
                    step.resources["order"] = self.resume
                return step
            else:
                logger.warning("No remaining steps available (%d)" % self.job_id)
                return None

    def _set_error(self):
        pass

    def prepare_workspace(self):
        """
        Build path info for the execution of a job
        :return: tuple, path to user folder and job folder
        """
        if self._result is None or self._resume == 0:
            result_store = rand_sig() + str(self.job_id)
            user_folder = os.path.join(self._work_dir, str(self._user.id))
            run_folder = os.path.join(user_folder, result_store)
            try:
                if not os.path.exists(user_folder):
                    os.mkdir(user_folder)
                if not os.path.exists(run_folder):
                    os.mkdir(run_folder)
                self.db_obj.set_result(result_store)
            except Exception as e:
                logger.exception(e)
        else:
            result_store = self._result
            user_folder = os.path.join(self._work_dir, str(self._user.id))
            run_folder = os.path.join(user_folder, result_store)

        self._user_folder = user_folder
        self._run_folder = run_folder
        self._result_store = result_store
        return user_folder, run_folder, result_store

    @staticmethod
    def build_special_parameter_dict(all_output):
        special_dict = {}
        if all_output.find(';') != -1:
            options = all_output.split(';')
            if '' in options:
                options.remove('')
            for option in options:
                tmp = option.split('=')
                if len(tmp) == 2:
                    k, v = tmp
                    k.strip()
                    v.strip()
                    special_dict[k] = v
                else:
                    continue
        return special_dict

    def initialize_job_parameters(self, ref_dict):
        """
        Parse reference and job parameter (special and input files)

        Parameters
        ----------
        ref_dict : dict
            A dictionary of user's references (keys are names of refs)

        Returns
        -------

        """
        # JOB_PARAMETERS[job_id] = parameterParser.build_special_parameter_dict(job_parameter)
        self._job_parameters = Task.build_special_parameter_dict(self._parameter)
        # get_user_reference(user)
        # if user in USER_REFERENCES:
        if ref_dict is not None:
            self._job_parameters = dict(self._job_parameters, **ref_dict)
        # JOB_INPUT_FILES[job_id] = input_file.split(';') now available at self._job_input_files
        # INPUT_SIZE[job_id] = 0

    def set_checkpoint_info(self, checkpoint):
        self.db_obj.wait_for = checkpoint
        self.db_obj.status = _JS_RESOURCELOCK
        self.db_obj.save()

    @staticmethod
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
            if suffix in suffix_dict:
                suffix_dict[suffix].append(output_file)
            else:
                suffix_dict[suffix] = [output_file]
        return suffix_dict

    def update_job_file_mapping(self):
        this_output = bases.get_folder_content(self.run_folder)
        self.newfiles = sorted(list(set(this_output).difference(set(self.last_output))))
        self.newfiles = [os.path.join(self.run_folder, file_name) for file_name in self.newfiles]
        self.outputs.extend(self.newfiles)

        suffix_dict = self.build_suffix_dict(self.newfiles)
        self.output_dict[self.resume] = self.newfiles
        self.output_dict_suffix[self.resume] = suffix_dict
        self.last_output_suffix = suffix_dict
        self.last_output_string = " ".join(self.newfiles)
        self.output_size = bases.get_folder_size(self.run_folder) - self._folder_size_before
        self._cumulative_output_size += self.output_size

    def snapshot(self):
        """
        Create snapshot for a job

        :return:
        """
        snapshot = ConfigParser()
        snapshot.optionxform = str
        snapshot['input'] = dict()
        snapshot['output'] = dict()

        if os.path.exists(self.run_folder):
            for f in os.listdir(self.run_folder):
                if f == ".snapshot.ini":
                    continue
                full_path = os.path.join(self.run_folder, f)
                if os.path.isfile(full_path):
                    ctime = os.path.getctime(full_path)
                    mtime = os.path.getmtime(full_path)
                    fbytes = os.path.getsize(full_path)
                    snapshot['output'][f] = "%d;%d;%d" % (ctime, mtime, fbytes)

            parsed_uploaded_files, _ = _Step._upload_file_map(self._job_input, self.user_folder)
            parsed_history_files, _, _ = _Step._history_map(parsed_uploaded_files, self._user)
            parsed_inputs = parsed_history_files.split(";")
            for input_file in parsed_inputs:
                if os.path.exists(input_file) and os.path.isfile(input_file):
                    ctime = os.path.getctime(input_file)
                    mtime = os.path.getmtime(input_file)
                    fbytes = os.path.getsize(input_file)
                    snapshot['input'][input_file] = "%d;%d;%d" % (ctime, mtime, fbytes)

            with open(os.path.join(self.run_folder, ".snapshot.ini"), 'w') as configfile:
                snapshot.write(configfile)


class JobQueue(object):
    def __init__(self, max_job, cpu_pool, memory_pool, disk_pool, work_dir, settings, n_retries=3):
        self._CPU_POOL = cpu_pool
        self._MEMORY_POOL = memory_pool
        self._DISK_POOL = disk_pool
        self.WORK_DIR = work_dir
        self.MAX_JOB = int(max_job) if max_job != "" else 0
        self._RUNNING_TABLE = set()
        self._STEP_DEPENDENCIES = dict()
        self._USER_REFERENCES = dict()
        self.RUN_PARAMETERS = dict()
        self.FOLDER_SIZE_BEFORE = dict()
        self._RESOURCES = dict()
        self.LATEST_JOB_ID = 0
        self.LATEST_JOB_STEP = 0
        self._RUNNING_STEPS = 0
        self._QUEUE = dict()
        self._PROTOCOL_CACHE = dict()
        self._lock = threading.Lock()
        self._is_queue_locked = 0
        self._failed_tasks = set()
        self._db_fail_msg_tpl = "Cannot synchronize result to database for {job} ({operation})"
        self._settings = settings
        self._n_retries = 1
        self.n_retries = n_retries
        super(JobQueue, self).__init__()

    def dequeue(self, job, is_error=0):
        """
        Pop a job out of the queue and finish the following steps

        1.
        Parameters
        ----------
        job :

        Returns
        -------

        """
        with self._lock:
            for _ in range(self.n_retries):
                try:
                    if is_error:
                        job.db_obj.status = _JS_WRONG
                        job.db_obj.ter = 0
                    else:
                        job.db_obj.status = _JS_FINISHED
                    job.db_obj.save()
                    break
                except Exception as e:
                    self._failed_tasks.add((self.dequeue, job.job_id))
                    logger.warning(self._db_fail_msg_tpl.format(job=job.job_id, operation="dequeue"))
                    logger.warning(e)
            try:
                self.remove_resources(job.job_id)
                if not is_error:
                    job.snapshot()
                bases.save_output_dict(job.file_map, job.job_id)
            except Exception as e:
                logger.exception(e)
            finally:
                del self._QUEUE[job.job_id]

    def enqueue(self, job):
        """
        Put a job into queue and finish the following tasks

        1. create workdir if it's not exists
        2. initialize dict of job parameters
        3. push job into queue

        Parameters
        ----------
        job : Task
            A job instance

        Returns
        -------

        """
        # check
        uf, rf, result = job.prepare_workspace()
        job.initialize_job_parameters(ref_dict=self._get_user_references(job._user))

        with self._lock:
            self._QUEUE[job.job_id] = job

    @staticmethod
    def clean_dead_jobs():
        # clean dead jobs
        try:
            djs = Job.objects.filter(Q(status=_JS_RUNNING) | Q(status=_JS_RESOURCELOCK))
            for j in djs:
                logger.warning(f"The status of job {j.job_name} ({j.id}) is {j.get_status_display()}, now BioQueue marks it as failed.")
                j.status = _JS_WRONG
                j.save()
        except Exception as e:
            logger.exception(e)

    # @property
    def get_queue(self):
        return self._QUEUE.copy()

    @property
    def get_resources(self):
        return sorted(self._RESOURCES.items(), key=lambda x: x[1]["cpu"] if x[1]["cpu"] is not None else 100)

    def set_resources(self, job, value):
        self._RESOURCES[job] = value

    def remove_resources(self, job):
        if job in self._RESOURCES:
            del self._RESOURCES[job]

    @property
    def running_jobs(self):
        return len(self._QUEUE)

    @property
    def running_steps(self):
        return self._RUNNING_STEPS

    @property
    def running_table(self):
        return self._RUNNING_TABLE

    @property
    def is_queue_locked(self):
        with self._lock:
            return self._is_queue_locked

    @is_queue_locked.setter
    def is_queue_locked(self, value):
        with self._lock:
            self._is_queue_locked = bool(value)

    @property
    def n_retries(self):
        return self._n_retries

    @n_retries.setter
    def n_retries(self, value):
        try:
            if int(value) > 0:
                self._n_retries = int(value)
            else:
                self._n_retries = 1
        except:
            self._n_retries = 1

    def _get_user_references(self, user):
        """

        Parameters
        ----------
        user_id :

        Returns
        -------

        @ todo: there's a conflict between user's ref and global ref, keep user's
        @ todo: cache queries?
        """
        results = Reference.objects.filter(Q(user=user) | Q(user=None)).order_by("user_id")
        refs = {}
        for ref in results:
            refs[ref.name] = ref.path
        return refs

    def _update_resource_pool(self, resource_dict, direction=1):
        """
        Update resource pool

        Parameters
        ----------
        cpu :
        mem :
        disk :

        Returns
        -------

        """
        with self._lock:
            if resource_dict["cpu"] is not None:
                self._CPU_POOL += resource_dict["cpu"] * direction
            if resource_dict["mem"] is not None:
                self._MEMORY_POOL += resource_dict["mem"] * direction
            if resource_dict["disk"] is not None:
                self._DISK_POOL += resource_dict["disk"] * direction
        return self._CPU_POOL, self._MEMORY_POOL, self._DISK_POOL

    def _parse_api_job(self, job_db_obj):
        protocol_cache_key = job_db_obj.protocol.ver
        pid = job_db_obj.protocol.id
        p_ver = job_db_obj.protocol_ver
        if pid in self._PROTOCOL_CACHE and self._PROTOCOL_CACHE[pid]["ver"] == p_ver:
            protocol = self._PROTOCOL_CACHE[pid]
        else:
            protocol = Protocol(poj=job_db_obj.protocol, settings=self._settings)
            self._PROTOCOL_CACHE[protocol_cache_key] = protocol

        # if the two versions are different, throw out a warning
        if p_ver != protocol.ver:
            logger.warning(
                "Job {job_id} is trying to use an outdated protocol (pid: {pid}, asked version: {av}, real version: {rv})".format(
                    job_id=job_db_obj.id, pid=pid, av=p_ver, rv=protocol.ver))

        # job_obj, protocol, settings
        job_obj = Task(job_obj=job_db_obj, protocol=protocol, settings=self._settings)
        return job_obj

    def fetch_jobs(self, n_jobs=None):
        if n_jobs is None:
            n_jobs = self.MAX_JOB - self.running_jobs
        try:
            jobs = Job.objects.filter(status=_JS_WAITING)[:n_jobs]
        except Exception as e:
            jobs = None
            logger.error("Error occurred when fetching new jobs from the database")
            logger.error(e)

        if jobs is not None and len(jobs) > 0:
            for job in jobs:
                if job.id not in self._QUEUE:  # not in queue
                    t_job = self._parse_api_job(job_db_obj=job)
                    self.enqueue(t_job)
                else:  # already in queue
                    continue

    def query_job_status(self, job_id):
        return Job.objects.get(id=job_id).status

    def forecast_step(self, step):
        """
        Before the running of a step
        :param job_id: int, job id
        :param step_order: int, step order
        :param resources: dictionary, resources required by the step
        :return: If system resources is not enough for the step, it will return False, otherwise, it returns True
        """
        rollback = 0

        if self._settings['cluster']['type'] == '':
            # for running on local machine
            if step.resources is not None and step.resources["cpu"] is not None and np.isnan(step.resources["cpu"]):
                return False
            new_cpu, new_mem, new_disk = self._update_resource_pool(step.resources, -1)

            if new_cpu < 0 or new_mem < 0 or new_disk < 0:
                rollback = 1

        if not rollback:
            return True
        else:
            if self._settings['cluster']['type'] == '':
                self._update_resource_pool(step.resources)
            return False

    @staticmethod
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

    def finish_step(self, job, is_error=0):
        """

        Parameters
        ----------
        job : Task

        is_error :

        Returns
        -------

        """
        resource = job.steps[job.resume].resources
        self._update_resource_pool(resource)

        if is_error:
            # step went wrong or job got terminated
            try:
                if 'trace' in resource:
                    try:
                        training = Training.objects.get(id=resource['trace'])
                        training.delete()
                    except:
                        pass
                self.dequeue(job, is_error=is_error)
            except:
                pass
        else:
            try:
                job.resume += 1
                job.db_obj.resume = job.resume
                logger.info(f"Synchronizing resume info {job.resume} for job {job.job_id} to the database")
                job.db_obj.save()
            except Exception as e:
                logger.error(f"Failed to update step status record for {job.job_id} ({job.resume}), details:")
                logger.exception(e)

            job.update_job_file_mapping()
            if "trace" in resource and resource["trace"] is not None:
                try:
                    training = Training.objects.get(id=resource['trace'])
                    training.output = job.output_size
                    training.lock = 0
                    training.save()
                except Exception as e:
                    logger.error(f"Failed to update training record ({resource['trace']}) for {job.job_id} ({job.resume}), details:")
                    logger.exception(e)

            if job.resume >= len(job.steps):
                self.dequeue(job)

    def _run_step_cluster(self, job, stdout_to, stderr_to):
        # for cluster
        import cluster_support
        step_obj = job.steps[job.resume]
        if step_obj.resources['cpu'] is None:
            allocate_cpu = step_obj['cluster']['cpu']
        else:
            from math import ceil
            predict_cpu = int(ceil(round(step_obj.resources['cpu']) / 100))
            if predict_cpu > self._settings['cluster']['cpu'] or predict_cpu == 0:
                allocate_cpu = self._settings['cluster']['cpu']
            else:
                allocate_cpu = predict_cpu
        if 'mem' not in step_obj.resources or step_obj.resources['mem'] is None:
            allocate_mem = self._settings['cluster']['mem']
        else:
            allocate_mem = bases.bytes_to_readable(step_obj.resources['mem'])
        if 'vrt_mem' not in step_obj.resources or step_obj.resources['vrt_mem'] is None:
            allocate_vrt = self._settings['cluster']['vrt']
        else:
            allocate_vrt = bases.bytes_to_readable(step_obj.resources['vrt_mem'])

        if 'trace' in step_obj.resources:
            # learn
            return_code = cluster_support.main(self._settings['cluster']['type'], ' '.join(step_obj.command),
                                               job.job_id, job.resume, allocate_cpu, allocate_mem, allocate_vrt,
                                               self._settings['cluster']['new_queue'], job.run_folder,
                                               stdout_to, self._settings['cluster']['walltime'], 1, job.resources['trace'])
        else:
            return_code = cluster_support.main(self._settings['cluster']['type'], ' '.join(step_obj.command),
                                               job.job_id, job.resume, allocate_cpu, allocate_mem, allocate_vrt,
                                               self._settings['cluster']['new_queue'], job.run_folder,
                                               stdout_to, self._settings['cluster']['walltime'])

        return return_code

    def _run_step_local(self, job, stdout_to, stderr_to):
        """

        Parameters
        ----------
        job : _Step

        Returns
        -------

        """
        # for local environment or cloud
        logger.info("Now run {job_id} - {step_id}".format(job_id=job.job_id, step_id=job.resume))
        logger.info("Resource pool: CPU {cpu}, Memory {mem}, Disk {disk}".format(cpu=self._CPU_POOL,
                                                                                 mem=self._MEMORY_POOL,
                                                                                 disk=self._DISK_POOL))

        if os.path.exists(self._settings["env"]["log"]):
            with open(stdout_to, "a") as log_file_handler:
                with open(stderr_to, "a") as err_file_handler:
                    try:
                        step_obj = job.steps[job.resume]
                        true_shell = bases.check_shell_sig(step_obj.command)
                        logger.info(step_obj.command)
                        if true_shell:
                            step_process = subprocess.Popen(' '.join(step_obj.command), shell=True,
                                                            stdout=log_file_handler,
                                                            stderr=err_file_handler,
                                                            cwd=job.run_folder)
                        else:
                            step_process = subprocess.Popen(step_obj.command, shell=False, stdout=log_file_handler,
                                                            stderr=err_file_handler, cwd=job.run_folder)

                        process_id = step_process.pid
                        if "learn" in step_obj.resources and step_obj.resources["learn"] == 1:
                            training = Training(step_hash=step_obj._md5_hex, input=job.input_size, lock=1)
                            training.save()
                            trace_id = training.id
                            step_obj.resources["trace"] = trace_id
                            learn_process = subprocess.Popen(["python", os.path.join(root_path, 'ml_collector.py'),
                                                              "-p", str(step_process.pid), "-n",
                                                              step_obj.md5_hex,
                                                              "-j", str(trace_id)],
                                                             shell=False, stdout=None,
                                                             stderr=subprocess.STDOUT)
                        # check if user requests for a termination
                        while step_process.poll() is None:
                            if process_id in psutil.pids():
                                proc_info = psutil.Process(process_id)
                                if proc_info.is_running():
                                    for _ in range(self.n_retries):
                                        try:
                                            _j = Job.objects.get(id=job.job_id)
                                            if _j.ter:
                                                JobQueue.kill_proc(proc_info)
                                                self.finish_step(job, is_error=1)
                                                return None
                                            break
                                        except Exception as e:
                                            logger.warning(f"Failed to retrieve job (id: {job.job_id}) status from the database")
                                            logger.exception(e)

                            time.sleep(30)
                        logger.info("Now job {job_id} - {step_id} finished ({rc})".format(job_id=job.job_id,
                                                                                          step_id=job.resume,
                                                                                          rc=step_process.returncode))
                        return step_process.returncode
                    except Exception as e:
                        logger.info(
                            "Job {job_id} - {step_id} failed".format(job_id=job.job_id, step_id=job.resume))
                        logger.exception(e)
                        log_file_handler.write(str(e)+"\n")
                        return 1

    def run_step(self, job_obj):
        current_job_id = job_obj.job_id
        step_obj = job_obj.steps[job_obj.resume]
        step_key = (current_job_id, job_obj.resume)
        with self._lock:
            step_obj.is_running = 1
            self._RUNNING_TABLE.add(step_key)

        if os.path.exists(self._settings["env"]["log"]):
            try:
                if not os.path.exists(job_obj.run_folder):
                    raise IOError("Cannot write content to {dest}".format(dest=job_obj.run_folder))
                # if recheck is ok, then update job status and run
                recheck = self.forecast_step(step_obj)

                if len(step_obj.dependent_jobs) > 0:
                    for sd in step_obj.dependent_jobs:
                        while self.query_job_status(job_id=sd.id) != -1:
                            # update checkpoint information for this job (waiting for dependent jobs)
                            job_obj.set_checkpoint_info(checkpoint=CheckPoints.DEPENDENCE)
                            time.sleep(30)

                log_file = os.path.join(self._settings["env"]["log"], "{job_id}.log".format(job_id=job_obj.job_id))
                errlog_file = os.path.join(self._settings["env"]["log"], "{job_id}.err".format(job_id=job_obj.job_id))

                if recheck is not True:
                    return

                with self._lock:
                    self._RUNNING_STEPS += 1
                try:
                    job_obj.db_obj.status = _JS_RUNNING
                    job_obj.db_obj.resume = job_obj.resume
                    job_obj.db_obj.save()
                except Exception as e:
                    logger.warning(self._db_fail_msg_tpl.format(job=current_job_id, operation="update step status"))
                    logger.warning(e)

                if self._settings['cluster']['type'] and not step_obj.force_local:
                    rc = self._run_step_cluster(job_obj, log_file, errlog_file)
                else:
                    logger.info(f"Projected resource usage: {step_obj.resources}")
                    rc = self._run_step_local(job_obj, log_file, errlog_file)

                if rc != 0:
                    self.finish_step(job_obj, is_error=1)
                else:
                    self.finish_step(job_obj, is_error=0)
            except Exception as e:
                logger.error("Error triggered by job {job_id} step {step_id}".format(job_id=current_job_id,
                                                                                     step_id=job_obj.resume))
                logger.exception(e)
            finally:
                with self._lock:
                    if step_key in self._RUNNING_TABLE:
                        self._RUNNING_TABLE.remove(step_key)
                        self._RUNNING_STEPS -= 1
                        step_obj.is_running = 0
        else:
            logger.error("Cannot access {path}".format(path=self._settings["env"]["log"]))
            self.finish_step(job_obj, is_error=1)
        # release the lock
        self.is_queue_locked = False


class CheckPoints(IntEnum):
    FINISHING = 0
    DISK = 1
    MEMORY = 2
    CPU = 3
    FORMER = 4
    PEER = 5
    DEPENDENCE = 6


def maintenance():
    pass


def check_settings(settings):
    return 1


def main(n_retries=3):
    logger.info("Initiating BioQueue worker")
    settings = get_all_config()
    assert check_settings(settings), "Settings is not valid"
    # check configuration
    CPU_POOL, MEMORY_POOL, DISK_POOL, VRT_POOL = get_init_resource()
    job_queue = JobQueue(max_job=settings["env"]["max_job"], cpu_pool=CPU_POOL,
                         memory_pool=MEMORY_POOL, disk_pool=DISK_POOL, work_dir=settings["env"]["workspace"],
                         settings=settings, n_retries=n_retries)
    job_queue.clean_dead_jobs()

    while True:
        try:
            settings = get_all_config()
            cpu_indeed = get_cpu_available()
            mem_indeed, vrt_indeed = get_memo_usage_available()
            disk_indeed = get_disk_free(settings["env"]["workspace"])

            job_queue.fetch_jobs()
            JOB_TABLE = job_queue.get_queue()
            sorted_jobs = {k: JOB_TABLE[k] for k in sorted(JOB_TABLE)}

            for job_id, job_obj in sorted_jobs.items():
                # previous_step = job_obj.get_prev_step()
                now_step = job_obj.get_current_step()

                if now_step is None or now_step.is_running:
                    continue

                job_queue.set_resources(job_id, now_step.resources)

            biggest_cpu = None
            biggest_mem = None
            biggest_job = None

            if job_queue.is_queue_locked:
                continue
            # greedy algorithm
            for index, job_desc in enumerate(job_queue.get_resources):
                # items = job_desc.split('_')
                job_id = job_desc[0]
                resource = job_desc[1]
                # step_order = int(items[1])
                job_obj = JOB_TABLE[job_id]
                step_order = job_obj.resume
                step_key = (job_id, job_obj.resume)

                if job_obj.status > 0 or step_key in job_queue.running_table or resource["order"] > step_order or job_obj.steps[job_obj.resume].is_running:
                    continue

                if resource['cpu'] is None \
                        and resource['mem'] is None \
                        and resource['disk'] is None:
                    if job_queue.running_steps > 0:
                        job_obj.set_checkpoint_info(CheckPoints.FORMER)
                    else:
                        # lock the queue to prevent other jobs also get into the queue
                        job_queue.is_queue_locked = True
                        new_thread = threading.Thread(target=job_queue.run_step, args=(job_obj, ))
                        new_thread.setDaemon(True)
                        new_thread.start()
                    break
                else:
                    if resource['cpu'] > cpu_indeed or resource['cpu'] > CPU_POOL:
                        job_obj.set_checkpoint_info(CheckPoints.CPU)
                    elif resource['mem'] > mem_indeed or resource['mem'] > MEMORY_POOL:
                        job_obj.set_checkpoint_info(CheckPoints.MEMORY)
                    elif "disk" in resource and (
                            resource['disk'] > disk_indeed or resource['disk'] > DISK_POOL):
                        job_obj.set_checkpoint_info(CheckPoints.DISK)
                    else:
                        if biggest_cpu is None:
                            biggest_cpu = resource['cpu']
                        if biggest_mem is None:
                            biggest_mem = resource['mem']
                        if biggest_job is None:
                            biggest_job = job_obj

                        if biggest_cpu < resource['cpu']:
                            biggest_cpu = resource['cpu']
                            biggest_mem = resource['mem']

                            biggest_job = job_obj
            if biggest_job is not None:
                new_thread = threading.Thread(target=job_queue.run_step, args=(biggest_job, ))
                new_thread.setDaemon(True)
                new_thread.start()
            biggest_job = None
            time.sleep(5)
        except Exception as e:
            logger.exception(e)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="BioQueue worker")
    parser.add_argument("--n-retry", default=3,
                        help="Number of retries allowed when a transaction to the database is failed")
    parser.add_argument("--concise", action="store_true", default=False,
                        help="Less verbose")
    args = parser.parse_args()

    if args.concise:
        level = logging.WARNING
    else:
        level = logging.INFO

    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)

    main(n_retries=args.n_retry)
