#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 6/23/20
import argparse
import os
import random
import shutil
import sys
import psutil
import django_initial
import re
import traceback
from enum import IntEnum
import threading
import time
import bases
import subprocess
import logging
import hashlib
import numpy as np
from fabric import Connection
from bases import *
from copy import copy
from _step import _Step
from django.db.models import Q
from QueueDB.models import Job, Step, Reference, Training, Slave, _JS_WAITING, _JS_RESOURCELOCK, _JS_RUNNING, _JS_FINISHED, _JS_WRONG

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
    def __init__(self, poj, settings, suffix=""):
        super(Protocol, self).__init__()
        # super(Protocol, self).__init__(poj, settings)
        self._ver = poj.ver
        # self.raw_steps = Step.objects.filter(parent=poj).order_by("step_order")
        self.protocol_file = f"{poj.id}-{poj.ver}{suffix}.sh"
        with open(os.path.join(settings["env"]["workspace"], "protocols", self.protocol_file)) as fh:
            self.protocol_content = fh.read()
        self._settings = settings

    @property
    def ver(self):
        return self._ver

    def customize_steps_by_user_dir(self, workspace_path, user_id) -> list[_Step]:
        step_list = []
        for index, step in enumerate(self.raw_steps):
            # priority for self-compiled tool
            sp = step.software

            if workspace_path is not None and os.path.exists(workspace_path):
                if user_id is not None:
                    software_path = os.path.join(os.path.join(os.path.join(workspace_path, str(user_id)), "bin"),
                                                 str(step.software))
                    if os.path.exists(software_path) and os.path.isfile(software_path):
                        sp = software_path

            step_list.append(_Step(software=sp.rstrip(),
                                   parameter=str(step.parameter),
                                   specify_output=step.specify_output,
                                   md5_hex=step.hash,
                                   env=step.env,
                                   version_check=step.version_check,
                                   force_local=step.force_local,
                                   settings=self._settings, 
                                   gpu_step=step.gpu_step))
        return step_list


class Task(object):
    def __init__(self, job_obj: Job, protocol: Protocol, settings):
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
        self._job_ver = job_obj.version
        self._user = job_obj.user
        self._status = job_obj.status
        self._protocol = copy(protocol)
        # self._work_dir = job_obj.run_dir
        self._work_dir = settings["env"]["workspace"]

        self.prev_step = None
        self.current_step = None

        self._parameter = job_obj.parameter

        self._result = job_obj.result
        self._resume = job_obj.resume
        self._wait_for = job_obj.wait_for

        # for translating protocol
        # self._steps = self._protocol.customize_steps_by_user_dir(workspace_path=self._work_dir, user_id=self._user.id)
        self._steps = [_Step(software="each", parameter="", specify_output="",
                             md5_hex="", env="", version_check="", force_local=0, settings=settings, 
                             gpu_step=0), ]
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
        self._assigned_gpu = None

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
        self._snapshot_file = ""

    def __str__(self):
        return "{job_name} ({job_id})".format(job_name=self.job_name, job_id=self.job_id)

    def __repr__(self):
        return self.__str__()

    @property
    def db_obj(self) -> Job:
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
    def job_ver(self):
        return self._job_ver
    
    @job_ver.setter
    def job_ver(self, ver):
        self._job_ver = ver
        self._db_obj.version = ver
        self._db_obj.save(update_fields=["version", "update_time"])

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
    def steps(self) -> list[_Step]:
        return self._steps

    @property
    def user_options(self):
        return self._job_parameters

    @property
    def work_dir(self) -> str:
        return self._work_dir

    @property
    def assigned_gpu(self) -> int:
        return self._assigned_gpu
    
    @assigned_gpu.setter
    def assigned_gpu(self, value):
        self._assigned_gpu = value

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
                    # step.translate_step_to_runnable(job=self)
                    pass

                if (step.resources is None or step.resources["learn"] == 1) and not step.is_running:
                    # no_new_learn
                    step.resources = step.predict_resources_needed(job=self)
                    step.resources = {'cpu': 0, 'mem': 0, 'disk': 0, 'vrt_mem': 0}
                    step.resources["order"] = self.resume
                    step.resources["learn"] = 0
                return step
            else:
                logger.warning("No remaining steps available (%d, %d, %d)" % (self.job_id, self.resume, len(self.steps)))
                return None

    def _set_error(self):
        pass

    def prepare_workspace(self):
        """
        Build path info for the execution of a job
        :return: tuple, path to user folder and job folder
        """
        if self._result is None or self._resume == 0:
            self.job_ver = self.job_ver + 1
            result_store = f"{self.job_id}v{self.job_ver}"
            user_folder = os.path.join(self._work_dir, str(self._user.id))
            run_folder = os.path.join(user_folder, result_store)
            try:
                if not os.path.exists(user_folder):
                    os.mkdir(user_folder)
                if not os.path.exists(run_folder):
                    os.mkdir(run_folder)
                if self._result is not None:
                    try:
                        target_dir = os.path.join(user_folder, self._result)
                        if not os.path.samefile(user_folder, target_dir):
                            shutil.rmtree(target_dir)
                    except:
                        pass
                self.db_obj.set_result(result_store)
            except Exception as e:
                logger.exception(e)
        else:
            result_store = self._result
            user_folder = os.path.join(self._work_dir, str(self._user.id))
            run_folder = os.path.join(user_folder, result_store)
            # in case I resume job across different machine
            if not os.path.exists(run_folder):
                source_folder = os.path.join(self._db_obj.run_dir, str(self._user.id), self._db_obj.result)
                source_folder = source_folder.replace("/local", "/fs/cbsuhy02")
                os.system(f"cp -r {source_folder} {user_folder}")

        self._user_folder = user_folder
        self._run_folder = run_folder
        self._result_store = result_store
        self.init_snapshot()
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
        self._protocol.protocol_content = self._protocol.protocol_content.replace("{{Job}}", str(self.job_id))
        self._protocol.protocol_content = self._protocol.protocol_content.replace("{{JobName}}", str(self.job_name))
        self._protocol.protocol_content = self._protocol.protocol_content.replace("{{LastOutput}}", self.last_output_string)
        self._protocol.protocol_content = self._protocol.protocol_content.replace("{{AllOutputBefore}}", " ".join(self.outputs))
        self._protocol.protocol_content = self._protocol.protocol_content.replace("{{Workspace}}", self.run_folder)
        self._protocol.protocol_content = _Step._last_output_map(self._protocol.protocol_content, self.newfiles)
        self._protocol.protocol_content = _Step._special_parameter_map(self._protocol.protocol_content, self.user_options)
        self._protocol.protocol_content = _Step._output_file_map(self._protocol.protocol_content, self.output_dict)
        self._protocol.protocol_content, outside_size = _Step._input_file_map(self._protocol.protocol_content, self.job_input_files, self.user_folder)
        self._protocol.protocol_content = _Step._suffix_map(self._protocol.protocol_content, self.output_dict_suffix, self.last_output_suffix)
        self._protocol.protocol_content, waiting_parent_1, is_error_1 = _Step._history_map(self._protocol.protocol_content, self.job_user)
        self._protocol.protocol_content, waiting_parent_2, is_error_2 = _Step._cross_access_map(self._protocol.protocol_content, self.job_user)

    def set_checkpoint_info(self, checkpoint):
        self.db_obj.wait_for = checkpoint
        self.db_obj.status = _JS_RESOURCELOCK
        self.db_obj.save(update_fields=["status", "wait_for", "update_time"])

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

    def init_snapshot(self):
        """
        Initiate a snapshot file

        Returns
        -------

        """
        expected_file = os.path.join(self.run_folder, ".snapshot.ini")
        if not os.path.exists(expected_file):
            snapshot = ConfigParser()
            snapshot.optionxform = str
            snapshot["input"] = dict()
            snapshot["output"] = dict()
            snapshot["version"] = dict()
            try:
                with open(expected_file, 'w') as configfile:
                    snapshot.write(configfile)
            except Exception as e:
                logger.error(e)
        self._snapshot_file = expected_file

    def update_snapshot(self, section, key, value):
        config_obj = ConfigParser()
        config_obj.optionxform = str
        if self._snapshot_file != "" and os.path.exists(self._snapshot_file):
            config_obj.read(self._snapshot_file)
            if config_obj.has_section(section):
                config_obj.set(section, key, value)
                with open(self._snapshot_file, "w") as fh:
                    config_obj.write(fh)
            else:
                logger.warning("Cannot update snapshot, the section ({0}) doesn't exist".format(section))
        else:
            logger.warning("Cannot update snapshot, file doesn't exist")

    def snapshot(self):
        """
        Create snapshot for a job

        :return:
        """
        snapshot = ConfigParser()
        snapshot.optionxform = str
        if self._snapshot_file != "" and os.path.exists(self._snapshot_file):
            snapshot.read(self._snapshot_file)

        if os.path.exists(self.run_folder):
            for f in os.listdir(self.run_folder):
                if f == ".snapshot.ini":
                    continue
                full_path = os.path.join(self.run_folder, f)
                if os.path.isfile(full_path):
                    ctime = os.path.getctime(full_path)
                    mtime = os.path.getmtime(full_path)
                    fbytes = os.path.getsize(full_path)
                    snapshot.set("output", f, "%d;%d;%d" % (ctime, mtime, fbytes))

            parsed_uploaded_files, _ = _Step._upload_file_map(self._job_input, self.user_folder)
            parsed_history_files, _, _ = _Step._history_map(parsed_uploaded_files, self._user)
            parsed_inputs = parsed_history_files.split(";")
            for input_file in parsed_inputs:
                if os.path.exists(input_file) and os.path.isfile(input_file):
                    ctime = os.path.getctime(input_file)
                    mtime = os.path.getmtime(input_file)
                    fbytes = os.path.getsize(input_file)
                    snapshot.set("input", input_file, "%d;%d;%d" % (ctime, mtime, fbytes))

            with open(self._snapshot_file, 'w') as configfile:
                snapshot.write(configfile)


class JobQueue(object):
    def __init__(self, max_job, cpu_pool, memory_pool, disk_pool, work_dir, settings, n_retries=3, targets=None):
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
        self._GPU_IN_USE = set()
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
        if settings["slave"]["hostname"] == "":
            raise ValueError("Hostname must not be empty!")

        if targets:
            self.target_machine = Slave.objects.filter(name__contains=targets)
        else:
            self.target_machine = None

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
                        job.db_obj.save(update_fields=["status", "ter", "update_time"])
                    else:
                        job.db_obj.status = _JS_FINISHED
                        job.db_obj.save(update_fields=["status", "update_time"])
                    # move results back to main repo
                    if job.db_obj.parent_job:
                        target_dir = os.path.join(job.db_obj.run_dir, str(job._user.id), job.db_obj.parent_job.result, str(job.db_obj.array_setting))
                        shutil.move(job.run_folder, target_dir)
                        job.db_obj.result = os.path.join(job.db_obj.parent_job.result, str(job.db_obj.array_setting))
                        job.db_obj.save(update_fields=["result"])
                        current_p = job.db_obj.parent_job
                        other_running_jobs = Job.objects.filter(parent_job=current_p, status__gte=0).count()
                        other_failed_jobs = Job.objects.filter(parent_job=current_p, status=_JS_WRONG).count()
                        if other_running_jobs == 0:
                            if other_failed_jobs > 0:
                                job.db_obj.parent_job.status = _JS_WRONG
                            else:
                                job.db_obj.parent_job.status = _JS_FINISHED
                            job.db_obj.parent_job.save(update_fields=["status"])
                    elif self._settings["slave"]["deposite_to"] != "":
                        # shutil.move(job.run_folder, os.path.join(self._settings["slave"]["deposite_to"], str(job._user.id)))
                        try:
                            os.system(f"rsync --archive --remove-source-files --partial {job.run_folder} {os.path.join(self._settings['slave']['deposite_to'], str(job._user.id))}")
                        except Exception as e:
                            logger.warning(e)
                        try:
                            logger.info(f"Copying {os.path.join(self._settings['env']['log'], str(job.job_id)+'.log')} to {os.path.join(self._settings['slave']['deposite_to'], 'logs')}")
                            shutil.copy(
                                os.path.join(self._settings["env"]["log"], str(job.job_id)+".log"), 
                                os.path.join(self._settings["slave"]["deposite_to"], "logs")
                            )
                        except Exception as e:
                            logger.warning(e)
                        try:
                            shutil.copy(
                                os.path.join(self._settings["env"]["log"], str(job.job_id)+".err"), 
                                os.path.join(self._settings["slave"]["deposite_to"], "logs")
                            )
                        except Exception as e:
                            logger.warning(e)
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
                if job.job_id in self._QUEUE:
                    del self._QUEUE[job.job_id]
                try:
                    # https://discord.com/api/webhooks/971424312038928505/6JUw41fWpE_yaifZ2Tr5lZh6B_A-YaqBOusRRSSsppFi6GFZLCv8zH4jcRnK3myvLM66
                    cmd_discord = "curl -s --connect-timeout 5 -H \"Content-Type: application/json\" -d '{\"content\": \"BioQueue analysis task %s (%d) %s.\"}' \"https://discord.com/api/webhooks/971424312038928505/6JUw41fWpE_yaifZ2Tr5lZh6B_A-YaqBOusRRSSsppFi6GFZLCv8zH4jcRnK3myvLM66\"" % (job.job_name, job.job_id, "failed" if is_error else "completed")
                    os.system(cmd_discord)
                except:
                    pass

    def enqueue(self, job: Task):
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

    def clean_dead_jobs(self):
        # clean dead jobs
        try:
            djs = Job.objects.filter(Q(status=_JS_RUNNING) | Q(status=_JS_RESOURCELOCK))
            djs = djs.filter(slave__in=self.target_machine)
            for j in djs:
                logger.warning(f"The status of job {j.job_name} ({j.id}) is {j.get_status_display()}, now BioQueue marks it as failed.")
                j.status = _JS_WRONG
                j.save(update_fields=["status", "update_time"])
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

    def _parse_api_job(self, job_db_obj) -> Task:
        protocol_cache_key = job_db_obj.protocol.ver
        pid = job_db_obj.protocol.id
        p_ver = job_db_obj.protocol_ver
        if pid in self._PROTOCOL_CACHE and self._PROTOCOL_CACHE[pid]["ver"] == p_ver:
            protocol = self._PROTOCOL_CACHE[pid]
        else:
            if job_db_obj.array_setting and job_db_obj.array_setting.find("--") != -1:
                protocol = Protocol(poj=job_db_obj.protocol, settings=self._settings, suffix=f"-{job_db_obj.slave.name}.arr")
            else:
                protocol = Protocol(poj=job_db_obj.protocol, settings=self._settings, suffix=f"-{job_db_obj.slave.name}")
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
            logger.debug(f"Fetching up to {n_jobs} jobs from the central database")
            jobs = Job.objects.filter(status=_JS_WAITING, slave__in=self.target_machine, is_gpu_job=1)[:n_jobs]
            logger.debug(f"Fetched {jobs.count()} jobs from the central database")
        except Exception as e:
            jobs = None
            logger.error("Error occurred when fetching new jobs from the database")
            logger.error(e)

        if jobs is not None and len(jobs) > 0:
            for job in jobs:
                if job.id not in self._QUEUE:  # not in queue
                    t_job = self._parse_api_job(job_db_obj=job)
                    logger.debug(f"Pushing job {t_job.job_id} into the queue")
                    self.enqueue(t_job)
                else:  # already in queue
                    continue

    def query_job_status(self, job_id):
        return Job.objects.get(id=job_id).status
    
    def get_gpu_available(self):
        import GPUtil
        deviceIDs = GPUtil.getAvailable(
            order = 'memory', maxLoad = 0.5, 
            maxMemory = 0.5, includeNan=False, 
            excludeID=list(self._GPU_IN_USE), excludeUUID=[], limit = 1)
        return deviceIDs

    def forecast_step(self, step: _Step):
        """
        Before the running of a step

        Parameters
        ----------
        step

        Returns
        -------

        """
        return True
        rollback = 0

        if self._settings['cluster']['type'] == '':
            # for running on local machine
            if step.resources is not None and step.resources["cpu"] is not None and np.isnan(step.resources["cpu"]):
                return False
            new_cpu, new_mem, new_disk = self._update_resource_pool(step.resources, -1)

            if new_cpu < 0 or new_mem < 0 or new_disk < 0:
                rollback = 1
            if step.gpu_step:
                has_available_gpu = len(self.get_gpu_available())
                if has_available_gpu < 1:
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

    def finish_step(self, job: Task, is_error=0):
        """

        Parameters
        ----------
        job : Task

        is_error :

        Returns
        -------

        """
        step_obj = job.steps[job.resume]
        resource = step_obj.resources
        self._update_resource_pool(resource)
        try:
            self._GPU_IN_USE.remove(step_obj.assigned_gpu)
        except:
            pass

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
            except Exception as e:
                logger.exception(e)
        else:
            try:
                job.resume += 1
                job.db_obj.resume = job.resume
                logger.info(f"Synchronizing resume info {job.resume} for job {job.job_id} to the database")
                job.db_obj.save(update_fields=["resume", "update_time"])
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

    def _run_step_cluster(self, ls_path: str, slave_obj: Slave, job_obj: Task, stdout: str, stderr: str, array_setting: str = ""):
        # for cluster
        regex = r"JobState=([a-zA-Z]+)"
        exit_regex = r"ExitCode=(\d+):(\d+)"
        slurm_id = None
        remote_done = False
        return_code = 255
        try:
            for _ in range(5):
                try:
                    with Connection(slave_obj.ssh_connection, user=slave_obj.ssh_user, 
                                    connect_kwargs={"key_filename": slave_obj.ssh_key}) as c:
                        # if the job is not submitted
                        if slurm_id is None:
                            # first copy the script to the server
                            remote_job_file = os.path.join(
                                f"/home/{slave_obj.ssh_user}/Documents/launch_scripts/",
                                os.path.split(ls_path)[1]
                                )
                            logger.info(f"Uploading job script for job {job_obj.job_id} to the cluster ({slave_obj.ssh_connection})")
                            c.put(ls_path, remote_job_file)
                            # submit the job
                            safe_array_setting = ""
                            if array_setting.strip().startswith("-"):
                                safe_array_setting = array_setting
                            logger.debug(f"{slave_obj.cluster_manager_path}sbatch {safe_array_setting} --requeue {remote_job_file}")
                            slurm_id = c.run(f"{slave_obj.cluster_manager_path}sbatch {safe_array_setting} --requeue {remote_job_file}", hide=True).stdout.replace("Submitted batch job", "").strip()
                            logger.info(f"{job_obj.job_id} is submitted to the cluster ({slave_obj.ssh_connection}) with job id {slurm_id}")
                        while True:
                            _j = Job.objects.get(id=job_obj.job_id)
                            if _j.ter:
                                c.run(f"{slave_obj.cluster_manager_path}scancel {slurm_id}")
                                return_code = 2
                                break
                            else:
                                scontrol_out = c.run(f"{slave_obj.cluster_manager_path}scontrol show job {slurm_id}", hide=True).stdout
                                matches = re.findall(regex, scontrol_out)
                                logger.debug(f"Job {job_obj.job_id} statues: {matches}")
                                if len(matches) > 0:
                                    if all([s in {"COMPLETED", "FAILED", "CANCELLED",} for s in matches]):
                                        logger.debug(f"Job {job_obj.job_id} triggered completion entrypoint")
                                        remote_done = True
                                        # exit_code, _ = re.findall(exit_regex, scontrol_out)[0]
                                        return_code = 255 if any([s == "CANCELLED" for s in matches]) else max(
                                            [int(e) for e, _ in re.findall(exit_regex, scontrol_out)])
                                        remote_result_dir = f"/home/{slave_obj.ssh_user}/workdir/{slurm_id}/"
                                        # download results
                                        sync_cmd = f"rsync --archive --compress --partial {slave_obj.ssh_user}@{slave_obj.ssh_connection}:{remote_result_dir} {job_obj.run_folder}/"
                                        try:
                                            os.system(sync_cmd)
                                        except Exception as e:
                                            logger.warning(e, stack_info=True)
                                        try:
                                            c.get(f"/home/{slave_obj.ssh_user}/slurm_outputs/{job_obj.job_id}.out", stdout)
                                        except Exception as e:
                                            logger.warning(e, stack_info=True)
                                        try:
                                            c.get(f"/home/{slave_obj.ssh_user}/slurm_outputs/{job_obj.job_id}.err", stderr)
                                        except Exception as e:
                                            logger.warning(e, stack_info=True)
                                        try:
                                            c.run(f"rm -rf {remote_result_dir}", hide=True)
                                        except Exception as e:
                                            logger.warning(e, stack_info=True)
                                        break
                                    # elif status in {"FAILED", "CANCELLED",}:
                                    #     return_code = 128
                                    #     break
                                    elif any([s in {"RUNNING", "COMPLETING", } for s in matches]):
                                        if job_obj.db_obj.status == -2:
                                            logger.debug(f"Job {job_obj.job_id} triggered running entrypoint")
                                            job_obj.db_obj.status = 1
                                            job_obj.db_obj.save(update_fields=["status", "update_time"])
                                    elif any([s in {"PENDING", } for s in matches]):
                                        logger.debug(f"Job {job_obj.job_id} triggered pending entrypoint")
                                        job_obj.set_checkpoint_info(5)
                                    elif any([s in {"CONFIGURING", } for s in matches]):
                                        logger.debug(f"Job {job_obj.job_id} triggered configuring entrypoint")
                                        job_obj.set_checkpoint_info(8)
                            time.sleep(random.randint(60, 180))
                        if remote_done:
                            break
                except Exception as e:
                    logger.info(e)
        except Exception as e:
            logger.warning(e, stack_info=True)
            return_code = 255
        return return_code

    def run_step(self, job_obj: Task):
        current_job_id = job_obj.job_id
        step_obj = job_obj.steps[job_obj.resume]
        step_key = (current_job_id, job_obj.resume)
        with self._lock:
            step_obj.is_running = 1
            self._RUNNING_TABLE.add(step_key)
            self._RUNNING_STEPS += 1
        slave_obj = job_obj.db_obj.slave
        array_setting = job_obj.db_obj.array_setting
        # build the job script
        poj = job_obj._protocol
        ls_file = f"{current_job_id}-{job_obj._job_ver}-{poj.ver[:8]}-{hashlib.md5(poj.protocol_content.encode('utf-8')).hexdigest()[:8]}.sh"
        ls_path = os.path.join(self._settings["env"]["workspace"], "launch_scripts", ls_file)
        with open(ls_path, "w") as fh:
            fh.write(job_obj._protocol.protocol_content)

        is_error = 0
        if os.path.exists(self._settings["env"]["log"]):
            try:
                if not os.path.exists(job_obj.run_folder):
                    raise IOError("Cannot write content to {dest}".format(dest=job_obj.run_folder))
                log_file = os.path.join(self._settings["env"]["log"], "{job_id}.log".format(job_id=job_obj.job_id))
                errlog_file = os.path.join(self._settings["env"]["log"], "{job_id}.err".format(job_id=job_obj.job_id))

                try:
                    job_obj.db_obj.status = _JS_RUNNING
                    job_obj.db_obj.resume = job_obj.resume
                    job_obj.db_obj.save(update_fields=["resume", "status", "update_time"])
                except Exception as e:
                    logger.warning(self._db_fail_msg_tpl.format(job=current_job_id, operation="update step status"))
                    logger.warning(e)

                rc = self._run_step_cluster(ls_path, slave_obj, job_obj, log_file, errlog_file, array_setting if array_setting else "")
                
                if rc != 0:
                    is_error = 1
            except Exception as e:
                is_error = 1
                logger.error("Error triggered by job {job_id} step {step_id}".format(job_id=current_job_id,
                                                                                     step_id=job_obj.resume))
                logger.exception(e)
            finally:
                self.finish_step(job_obj, is_error=is_error)
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
    GPU = 7


def maintenance():
    pass


def check_settings(settings):
    return 1


def main(n_retries=3, targets=None):
    logger.info(f"Initiating BioQueue worker (target machines: {targets})")
    settings = get_all_config(suffix="-slurm")
    print(settings)
    assert check_settings(settings), "Settings is not valid"
    # check configuration
    CPU_POOL, MEMORY_POOL, DISK_POOL, VRT_POOL = get_init_resource()
    job_queue = JobQueue(max_job=settings["env"]["max_job"], cpu_pool=CPU_POOL,
                         memory_pool=MEMORY_POOL, disk_pool=DISK_POOL, work_dir=settings["env"]["workspace"],
                         settings=settings, n_retries=n_retries, targets=targets)
    job_queue.clean_dead_jobs()

    while True:
        try:
            settings = get_all_config(suffix="-slurm")
            cpu_indeed = get_cpu_available()
            mem_indeed, vrt_indeed = get_memo_usage_available()
            disk_indeed = get_disk_free(settings["env"]["workspace"])

            job_queue.fetch_jobs()
            JOB_TABLE = job_queue.get_queue()
            sorted_jobs = {k: JOB_TABLE[k] for k in sorted(JOB_TABLE)}
            logger.debug(sorted_jobs.keys())

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
                print(resource)
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
    parser.add_argument("--debug", action="store_true", default=False,
                        help="Very verbose")
    parser.add_argument("-m", "--target-machines", type=str, required=True, help="Target machines")
    args = parser.parse_args()

    if args.concise:
        level = logging.WARNING
    elif args.debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)

    main(n_retries=args.n_retry, targets=args.target_machines)
