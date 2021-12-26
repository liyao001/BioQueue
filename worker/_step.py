#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Li Yao
# @Date: 1/3/21
# 
# BioQueue is free for personal use and is licensed under
# the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, 
# or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
import sys

import bases
import re
import os
import html
import logging
from scipy.stats import linregress
import numpy as np
from QueueDB.models import Job, Training, Prediction, _JS_FINISHED, _JS_WRONG, _PD_DISK, _PD_MEM, _PD_CPU, _PD_VRTMEM
logger = logging.getLogger("BioQueue - Step")


class _Step(object):
    def _predict_resource(self):
        pass

    def __init__(self, software, parameter, specify_output, md5_hex, env, force_local, version_check, settings):
        self._software = software
        self._parameter = parameter
        self._command = html.unescape(str(self._software).rstrip() + " " + str(self._parameter))
        self._specify_output = specify_output
        self._md5_hex = md5_hex
        self._env = env
        self._force_local = force_local
        self._cpu = None
        self._mem = None
        self._disk = None
        self._settings = settings
        self._translated_command = ""
        self._resources = None
        self._is_running = False
        self._ver_check = version_check
        self._dependent_jobs = set()
        self._prev_error_jobs = set()

    def __str__(self):
        if self._translated_command != "":
            return self._translated_command
        else:
            return self._command

    def __repr__(self):
        return self.__str__()

    @property
    def translated_command(self):
        return self._translated_command

    @property
    def resources(self):
        return self._resources

    @resources.setter
    def resources(self, value):
        if type(value) is dict:
            mandatory_keys = ("cpu", "mem", "vrt_mem", "disk")
            # auxiliary keys and their default values
            auxiliary_keys = {"trace": None, }
            if all([mk in value for mk in mandatory_keys]):
                for k, v in auxiliary_keys.items():
                    if k not in value:
                        value[k] = v
                self._resources = value
            else:
                print("Not all mandatory keys are present (Step, resources)")
        else:
            print("Value for resources should be a dict")

    @property
    def dependent_jobs(self):
        return self._dependent_jobs

    def add_dependent_jobs(self, dj):
        self._dependent_jobs.add(dj)

    def remove_dependent_jobs(self, dj):
        if dj in self._dependent_jobs:
            self._dependent_jobs.remove(dj)

    @property
    def software(self):
        return self._software

    @property
    def parameter(self):
        return self._parameter

    @property
    def command(self):
        return self._translated_command

    @property
    def md5_hex(self):
        return self._md5_hex

    @property
    def force_local(self):
        return self._force_local

    @property
    def is_running(self):
        return self._is_running

    @property
    def version_check(self):
        return self._ver_check

    @is_running.setter
    def is_running(self, value):
        try:
            self._is_running = bool(value)
        except:
            pass

    @staticmethod
    def _last_output_map(par, new_files):
        for key, value in enumerate(new_files):
            par = par.replace('{{LastOutput:' + str(key + 1) + '}}', value)
        return par

    @staticmethod
    def _special_parameter_map(par, sp_map):
        for keyword in sp_map.keys():
            pure_key = sp_map[keyword].replace('{{', '').replace('}}', '')
            if pure_key in sp_map.keys():
                sp_map[keyword] = sp_map[pure_key]
        for keyword in sp_map.keys():
            key_default = keyword.split('||')
            if len(key_default) == 2 and sp_map[keyword] == '':
                # if the parameter is not specified, then use default value
                par = par.replace('{{' + keyword + '}}', key_default[1])
            else:
                par = par.replace('{{' + keyword + '}}', sp_map[keyword])
        return par

    @staticmethod
    def _output_file_map(par, output_dict):
        output_replacement = re.compile("\\{\\{Output:(\\d+)-(\\d+)\\}\\}", re.IGNORECASE | re.DOTALL)
        for out_item in re.findall(output_replacement, par):
            if int(out_item[0]) in output_dict and (int(out_item[1]) - 1) < len(output_dict[int(out_item[0])]):
                par = par.replace('{{Output' + out_item[0] + '-' + out_item[1] + '}}',
                                  output_dict[int(out_item[0])][int(out_item[1]) - 1])
        return par

    @staticmethod
    def _upload_file_map(par, user_folder):
        filesize = 0
        uploaded_replacement = re.compile("\\{\\{Uploaded:(.*?)}}", re.IGNORECASE | re.DOTALL)
        for uploaded_item in re.findall(uploaded_replacement, par):
            upload_file = bases.build_upload_file_path(user_folder, uploaded_item)
            if upload_file is not None and upload_file != '':
                par = par.replace('{{Uploaded:' + uploaded_item + '}}', upload_file)
                filesize += os.path.getsize(upload_file)
        return par, filesize

    @staticmethod
    def _input_file_map(par, ini_dict, user_folder):
        file_size = 0
        if par.find('{{InputFile}}') != -1:
            init_input = ''
            for key, value in enumerate(ini_dict):
                if value.find("{{Uploaded:") == -1:
                    file_size += bases.get_remote_size_factory(value)
                    init_input += value + ' '
                else:
                    upload_path, upload_size = _Step._upload_file_map(value, user_folder)
                    file_size += upload_size
                    init_input += upload_path + ' '
            par = par.replace('{{InputFile}}', init_input)

        for key, value in enumerate(ini_dict):
            if par.find('{{InputFile:' + str(key + 1) + '}}') != -1:
                if value.find("{{Uploaded:") == -1:
                    par = par.replace('{{InputFile:' + str(key + 1) + '}}', value)
                    file_size += bases.get_remote_size_factory(value)
                else:
                    upload_path, upload_size = _Step._upload_file_map(value, user_folder)
                    file_size += upload_size
                    par = par.replace('{{InputFile:' + str(key + 1) + '}}', upload_path)
        par, upload_size = _Step._upload_file_map(par, user_folder)
        file_size += upload_size
        return par, file_size

    @staticmethod
    def _suffix_map(par, job_suffix_dict, last_suffix_dict):
        for key in last_suffix_dict.keys():
            par = par.replace('{{Suffix:' + key + '}}', ' '.join(last_suffix_dict[key]))
        suffix_replacement_single = re.compile("\\{\\{Suffix:(\\d+)-(.*?)\\}\\}", re.IGNORECASE | re.DOTALL)
        for suf_item in re.findall(suffix_replacement_single, par):
            job_step = int(suf_item[0])
            if job_step in job_suffix_dict.keys() and suf_item[1] in job_suffix_dict[job_step].keys():
                par = par.replace('{{Suffix:' + suf_item[0] + '-' + suf_item[1] + '}}',
                                  ' '.join(job_suffix_dict[job_step][suf_item[1]]))
        suffix_replacement_single = re.compile("\\{\\{Suffix:(\\d+)-(.*?)-(\\d+)\\}\\}", re.IGNORECASE | re.DOTALL)
        for suf_item in re.findall(suffix_replacement_single, par):
            job_step = int(suf_item[0])
            file_order = int(suf_item[2]) - 1
            if job_step in job_suffix_dict.keys() and suf_item[1] in job_suffix_dict[job_step].keys() \
                    and file_order < len(job_suffix_dict[job_step][suf_item[1]]):
                par = par.replace('{{Suffix:' + suf_item[0] + '-' + suf_item[1] + '-' + suf_item[2] + '}}',
                                  job_suffix_dict[job_step][suf_item[1]][file_order])
        return par

    @staticmethod
    def _history_map(par, user):
        need_to_wait = set()
        error_flag = 0
        history_replacement = re.compile("\\{\\{History:(\\d+)-(.*?)\\}\\}", re.IGNORECASE | re.DOTALL)
        for history_item in re.findall(history_replacement, par):
            history_id = int(history_item[0])
            history_file = history_item[1]
            try:
                history_record = Job.objects.get(id=history_id, user=user)
                if history_record.status > _JS_FINISHED:  # dependent job is still running
                    need_to_wait.add(history_id)
                elif history_record.status == _JS_WRONG:  # dependent job is malformed
                    error_flag = 1
                    need_to_wait.add(history_id)
                history_rep = os.path.join(history_record.run_dir, str(user.id), history_record.result)
                history_rep = os.path.join(history_rep, history_file)
                par = par.replace('{{History:' + str(history_id) + '-' + history_file + '}}', history_rep)
            except Exception as e:
                logger.exception(e)

        return par, need_to_wait, error_flag

    @staticmethod
    def _parameter_string_to_list(par):
        import shlex
        parameter_string = shlex.shlex(par)
        parameter_string.quotes = '"'
        parameter_string.whitespace_split = True
        parameter_string.commenters = ''
        parameters = list(parameter_string)
        return parameters

    def translate_step_to_runnable(self, job):
        """

        Parameters
        ----------
        job :
        connector :

        Returns
        -------

        """
        learning = 0
        outside_size = 0

        self._command = self._command.replace("{{Job}}", str(job.job_id))
        self._command = self._command.replace("{{JobName}}", str(job.job_name))

        self._command = self._command.replace("{{LastOutput}}", job.last_output_string)
        self._command = self._command.replace("{{AllOutputBefore}}", " ".join(job.outputs))
        self._command = _Step._last_output_map(self._command, job.newfiles)
        self._command = _Step._special_parameter_map(self._command, job.user_options)
        self._ver_check = _Step._special_parameter_map(self._ver_check, job.user_options)
        self._command = _Step._output_file_map(self._command, job.output_dict)
        self._command, outside_size = _Step._input_file_map(self._command, job.job_input_files, job.user_folder)
        self._command = _Step._suffix_map(self._command, job.output_dict_suffix, job.last_output_suffix)
        self._command, waiting_parent, is_error = _Step._history_map(self._command, job.job_user)
        for waiting_job in waiting_parent:
            self.add_dependent_jobs(waiting_job)
        self._command, outside_size_upload = _Step._upload_file_map(self._command, job.user_folder)
        outside_size += outside_size_upload
        self._command = self._command.replace("{{Workspace}}", job.run_folder)
        user_bin_dir = os.path.join(os.path.join(self._settings["env"]["workspace"], str(job.job_user.id), "bin"))
        if not os.path.exists(user_bin_dir):
            try:
                os.makedirs(user_bin_dir)
            except:
                pass
        self._command = self._command.replace("{{UserBin}}", user_bin_dir)
        if self._settings["cluster"]["type"]:
            if "cpu" in self._settings["cluster"] and self._settings["cluster"]["cpu"]:
                self._command = self._command.replace("{{ThreadN}}", str(self._settings["cluster"]["cpu"]))
            else:
                self._command = self._command.replace("{{ThreadN}}", str(self._settings["env"]["cpu"]))
        else:
            self._command = self._command.replace("{{ThreadN}}", str(self._settings["env"]["cpu"]))

        # support for virtual envs
        if self._env is not None and self._env.ve_type != "":
            # for conda environment
            if self._env.ve_type == "conda":
                if self._env.activation_command is not None and self._env.activation_command != "":
                    self._command = self._env.activation_command + " && conda activate " + self._env.value + "&&" + self._command
                    if self._ver_check != "":
                        self._ver_check = self._env.activation_command + " && conda activate " + self._env.value + "&&" + self._ver_check
                else:
                    self._command = "conda activate " + self._env.value + "&&" + self._command
                    if self._ver_check != "":
                        self._ver_check = self._env.activation_command + " && conda activate " + self._env.value + "&&" + self._ver_check
                self._command += " && conda deactivate"
                if self._ver_check != "":
                    self._ver_check += " && conda deactivate"

        self._translated_command = _Step._parameter_string_to_list(self._command)

    def get_training_items(self):
        """
        Get the amount of training items

        Parameters
        ----------
        connector :

        Returns
        -------

        """
        try:
            n = Training.objects.filter(step_hash=self._md5_hex, lock=0).count()
            return n
        except Exception as e:
            logger.exception(e)
            return 0

    def _load_train_frame(self):
        """
        load training items' frame
        :param step_hash: string, step hash
        :return:
        """
        raw_trainings = Training.objects.filter(step_hash=self._md5_hex, lock=0)
        tmp_x = []
        tmp_out = []
        tmp_mem = []
        tmp_vrt_mem = []
        tmp_cpu = []
        if raw_trainings is not None and len(raw_trainings) > 0:
            for t in raw_trainings:
                tmp_x.append(float(t.input) if t.input is not None else np.nan)
                tmp_out.append(float(t.output) if t.output is not None else np.nan)
                tmp_mem.append(float(t.mem) if t.mem is not None else np.nan)
                tmp_vrt_mem.append(float(t.vrt_mem) if t.vrt_mem is not None else np.nan)
                tmp_cpu.append(float(t.cpu) if t.cpu is not None else np.nan)

        return tmp_x, tmp_out, tmp_mem, tmp_cpu, tmp_vrt_mem

    def _regression_factory(self, save=0):
        """
        linear regression helper
        :param save:  int, 1 or 0. If save equals 1, the record will be saved to database
        :return: coefficients
        """
        coefficients = dict()
        try:
            x, out, mem, cpu, vrt_mem = self._load_train_frame()
            # o for output
            # m for memory
            # c for CPU
            # v for virtual memory
            for y, label in zip((out, mem, cpu, vrt_mem), ("o", "m", "c", "v")):
                if label == "c":
                    slope = 0
                    intercept = np.nanmean(y)
                    r = 1
                else:
                    slope, intercept, r, p, se = linregress(x, y)
                    coefficients["r_{l}".format(l=label)] = r
                if np.isnan(slope) or np.isnan(intercept):
                    coefficients["slope_{l}".format(l=label)] = 0
                    mean = np.nanmean(y)
                    coefficients["intercept_{l}".format(l=label)] = mean if not np.isnan(mean) else np.nan
                else:
                    if abs(r) > 0.8:
                        coefficients["slope_{l}".format(l=label)], coefficients[
                            "intercept_{l}".format(l=label)], = slope, intercept
                    else:
                        coefficients["slope_{l}".format(l=label)] = 0
                        coefficients["intercept_{l}".format(l=label)] = np.nanmean(y)

            if save:
                try:
                    Prediction(step_hash=self._md5_hex, a=coefficients["intercept_o"],
                               b=coefficients["slope_o"], r=coefficients["r_o"], type=_PD_DISK).save()
                    Prediction(step_hash=self._md5_hex, a=coefficients["intercept_m"],
                               b=coefficients["slope_m"], r=coefficients["r_m"], type=_PD_MEM).save()
                    Prediction(step_hash=self._md5_hex, a=coefficients["intercept_c"],
                               b=coefficients["slope_c"], r=coefficients["r_c"], type=_PD_CPU).save()
                    Prediction(step_hash=self._md5_hex, a=coefficients["intercept_v"],
                               b=coefficients["slope_v"], r=coefficients["r_v"], type=_PD_VRTMEM).save()
                except Exception as e:
                    logger.exception(e)

            return coefficients['slope_o'], coefficients['intercept_o'], \
                   coefficients['slope_m'], coefficients['intercept_m'], \
                   coefficients['slope_c'], coefficients['intercept_c'], \
                   coefficients['slope_v'], coefficients['intercept_v']
        except Exception as e:
            logger.exception(e)

    def _predict_factory(self, in_size=-99999.0, training_num=0):
        """
        Predict resource needed by a certain step
        :param in_size: float, input size
        :param training_num: int, number of training records
        :return: dict, resource dict
        """
        predict_need = {}
        try:
            equations = Prediction.objects.filter(step_hash=self._md5_hex)

            if len(equations) > 0 and in_size != -99999.0:
                for equation in equations:
                    a = float(equation.a)
                    b = float(equation.b)
                    t = equation.type
                    if t == 1:
                        predict_need['disk'] = (a * in_size + b) * float(self._settings['ml']['confidence_weight_disk'])
                    elif t == 2:
                        predict_need['mem'] = (a * in_size + b) * float(self._settings['ml']['confidence_weight_mem'])
                    elif t == 3:
                        predict_need['cpu'] = (a * in_size + b) * float(self._settings['ml']['confidence_weight_cpu'])
                    elif t == 4:
                        predict_need['vrt_mem'] = (a * in_size + b) * float(
                            self._settings['ml']['confidence_weight_mem'])
            else:
                if training_num < 1:
                    predict_need['cpu'] = None
                    predict_need['mem'] = None
                    predict_need['disk'] = None
                    predict_need['vrt_mem'] = None
                else:
                    if training_num < 10:
                        ao, bo, am, bm, ac, bc, av, bv = self._regression_factory(save=0)
                    else:
                        ao, bo, am, bm, ac, bc, av, bv = self._regression_factory()
                    if np.isnan(ao) or np.isnan(bo):
                        predict_need['disk'] = None
                    else:
                        predict_need['disk'] = int(
                            (ao * in_size + bo) * float(self._settings['ml']['confidence_weight_disk']))
                    if np.isnan(am) or np.isnan(bm):
                        predict_need['mem'] = None
                    else:
                        predict_need['mem'] = int(
                            (am * in_size + bm) * float(self._settings['ml']['confidence_weight_mem']))
                    if np.isnan(ac) or np.isnan(bc):
                        predict_need['cpu'] = None
                    else:
                        predict_need['cpu'] = int(
                            (ac * in_size + bc) * float(self._settings['ml']['confidence_weight_cpu']))
                    if np.isnan(av) or np.isnan(bv):
                        predict_need['vrt_mem'] = None
                    else:
                        predict_need['vrt_mem'] = int(
                            (av * in_size + bv) * float(self._settings['ml']['confidence_weight_mem']))

                    if any([pred is None for pred in predict_need.values()]):
                        return {'cpu': None, 'mem': None, 'disk': None, 'vrt_mem': None}
                    # in case the predicted value is negative (resources will be added to the pool)
                    if any([pred < -1 for pred in predict_need.values()]):
                        x, out, mem, cpu, vrt_mem = self._load_train_frame()
                        for pred_l, trainings in zip(("disk", "mem", "cpu", "vrt_mem"), (out, mem, cpu, vrt_mem)):
                            pred = predict_need[pred_l]
                            if pred <= 0:
                                predict_need[pred_l] = np.nanmean(trainings)

        except Exception as e:
            logger.exception(e)
            return {'cpu': None, 'mem': None, 'disk': None, 'vrt_mem': None}
        return predict_need

    def predict_resources_needed(self, job):
        """

        Parameters
        ----------
        job : Job

        connector : ApiAccess

        Returns
        -------

        """
        # LAST_OUTPUT[job_id] = baseDriver.get_folder_content(job['job_folder'])
        last_output = bases.get_folder_content(job.run_folder)
        training_num = self.get_training_items()

        if job.input_size == 0:
            job.input_size = bases.get_folder_size(job.run_folder)
        else:
            # if job_id in OUTPUT_SIZE:
            #     INPUT_SIZE[job_id] = OUTPUT_SIZE[job_id]
            # else:
            #     INPUT_SIZE[job_id] = 0
            pass
        folder_size_before = bases.get_folder_size(job.run_folder)
        job.output_size = folder_size_before
        job.input_size += job.output_size

        resource_needed = self._predict_factory(in_size=job.input_size, training_num=training_num)

        if resource_needed['cpu'] is not None and resource_needed['cpu'] > int(self._settings['env']['cpu']) * 100:
            resource_needed['cpu'] = int(self._settings['env']['cpu']) * 95

        no_new_learn = 0 if training_num < 10 else 1
        # if no_new_learn == 0:
        #     try:
        #         training = Training(step_hash=self._md5_hex, input=job.input_size, lock=1)
        #         training.save()
        #         trace_id = training.id
        #     except Exception as e:
        #         logger.exception(e)
        #         trace_id = None
        #     # resource_needed['trace'] = trace_id
        resource_needed['learn'] = 1 if training_num < 10 else 0

        return resource_needed
