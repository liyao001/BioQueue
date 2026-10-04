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

from worker import bases
import re
import os
import html
import logging
from scipy.stats import linregress
import numpy as np
from django.contrib.auth.models import User
from QueueDB.models import Job, Training, Prediction, CrossAccess, _JS_FINISHED, _JS_WRONG, _JS_INTERRUPTED, _PD_DISK, _PD_MEM, _PD_CPU, _PD_VRTMEM
logger = logging.getLogger("BioQueue - Step")


class _Step(object):
    def _predict_resource(self):
        pass

    def __init__(self, software, parameter, specify_output, md5_hex, env, force_local, version_check, settings, gpu_step: bool = False):
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
        self._gpu_step = gpu_step
        self._ver_check = version_check
        self._dependent_jobs = set()
        self._prev_error_jobs = set()
        self._assigned_gpu = None
        self._shell_script = ""
        self.shell_tag = _Step.SHELL_TAG

    SHELL_TAG = "__SHELL__"

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
    def is_shell(self):
        return str(self._software or "").strip() == self.SHELL_TAG

    def _strip_shell_tag(self, command):
        body = command.lstrip()
        tag = self.SHELL_TAG
        if body.startswith(tag):
            body = body[len(tag):]
            if body.startswith(" ") or body.startswith("\t"):
                body = body[1:]
        return body.lstrip("\n")

    @property
    def shell_script(self):
        return self._shell_script

    def write_shell_script(self, run_folder, step_index=0):
        """Write the translated shell body into the job folder for bash to run."""
        name = ".bq_step_{}.sh".format(step_index)
        path = os.path.join(run_folder, name)
        body = self._shell_script if self._shell_script else self._strip_shell_tag(self._command)
        if not body.endswith("\n"):
            body += "\n"
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env bash\n")
            fh.write(body)
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
        return path

    @property
    def parameter(self):
        return self._parameter

    @property
    def command(self):
        if self.is_shell:
            return self.shell_script
        return self._translated_command

    @property
    def md5_hex(self):
        return self._md5_hex
    
    @property
    def run_as_shell(self):
        if self.is_shell:
            return 1
        redirect_tags = ('>', '<', '|', ';', '*', '&&', '>>', '||', '$(')
        true_shell = 0
        try:
            for rt in redirect_tags:
                if rt in self._translated_command:
                    true_shell = 1
                    break
            for c in self._translated_command:
                if c.find("*") != -1 or c.startswith('"') or c.endswith('"') or c.find("$(") != -1:
                    true_shell = 1
                    break
            if self._translated_command and self._translated_command[0] == "R":
                true_shell = 1
        except Exception as e:
            logger.exception(e)
        return true_shell

    @property
    def force_local(self):
        return self._force_local

    @property
    def is_running(self):
        return self._is_running
    
    @is_running.setter
    def is_running(self, value):
        try:
            self._is_running = bool(value)
        except:
            pass

    @property
    def version_check(self):
        return self._ver_check
    
    @property
    def gpu_step(self):
        return self._gpu_step
    
    @property
    def assigned_gpu(self) -> int:
        return self._assigned_gpu
    
    @assigned_gpu.setter
    def assigned_gpu(self, value):
        self._assigned_gpu = value

    @staticmethod
    def _last_output_map(par, new_files):
        for key, value in enumerate(new_files):
            par = par.replace('{{LastOutput:' + str(key + 1) + '}}', value)
        return par

    @staticmethod
    def _special_parameter_map(par, sp_map):
        values = dict(sp_map)
        for keyword, value in values.items():
            pure_key = value.replace('{{', '').replace('}}', '')
            if pure_key in values:
                values[keyword] = values[pure_key]

        def replace(match):
            token = match.group(1)
            key, separator, default = token.partition('||')
            # Accept both current Key= values and legacy Key||default= values.
            value = values.get(key, values.get(token))
            if separator and value in (None, ''):
                return default
            return value if value is not None else match.group(0)

        for _ in range(6):
            resolved = re.sub(r'\{\{([^{}]+)\}\}', replace, par)
            if resolved == par:
                break
            par = resolved
        return par

    @staticmethod
    def _output_file_map(par, output_dict):
        output_replacement = re.compile("\\{\\{Output:(\\d+)-(\\d+)\\}\\}", re.IGNORECASE | re.DOTALL)

        def _repl(match):
            step_n = int(match.group(1))
            file_n = int(match.group(2))
            files = output_dict.get(step_n)
            if files is None:
                files = output_dict.get(str(step_n))
            if files is not None and (file_n - 1) < len(files):
                return files[file_n - 1]
            return match.group(0)

        return output_replacement.sub(_repl, par)

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
    def _parent_job_wait_state(status):
        """ready / wait / fail for a History or CrossAccess parent job."""
        if status == _JS_FINISHED:
            return "ready"
        if status in (_JS_WRONG, _JS_INTERRUPTED):
            return "fail"
        return "wait"

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
                state = _Step._parent_job_wait_state(history_record.status)
                if state == "wait":
                    need_to_wait.add(history_id)
                elif state == "fail":
                    error_flag = 1
                    need_to_wait.add(history_id)
                history_rep = os.path.join(history_record.run_dir, str(user.id), history_record.result)
                history_rep = os.path.join(history_rep, history_file)
                par = par.replace('{{History:' + str(history_id) + '-' + history_file + '}}', history_rep)
            except Exception as e:
                logger.exception(e)

        return par, need_to_wait, error_flag

    @staticmethod
    def _cross_access_map(par, user):
        need_to_wait = set()
        error_flag = 0
        ca_replacement = re.compile("\\{\\{CrossAccess:(\\d+)-(\\d+)-(.*?)\\}\\}", re.IGNORECASE | re.DOTALL)
        for ca_item in re.findall(ca_replacement, par):
            try:
                grantor = User.objects.get(id=int(ca_item[0]))
                access_record = CrossAccess.objects.get(user=grantor, grantee=user)
                if access_record.allow_read:
                    history_id = int(ca_item[1])
                    history_file = ca_item[2]
                    history_record = Job.objects.get(id=history_id, user=grantor)
                    state = _Step._parent_job_wait_state(history_record.status)
                    if state == "wait":
                        need_to_wait.add(history_id)
                    elif state == "fail":
                        error_flag = 1
                        need_to_wait.add(history_id)
                    history_rep = os.path.join(history_record.run_dir, str(grantor.id), history_record.result)
                    history_rep = os.path.join(history_rep, history_file)
                    par = par.replace('{{CrossAccess:' + ca_item[0] + '-' + str(history_id) + '-' + history_file + '}}', history_rep)
                else:
                    logger.error("User {0} doesn't have read access for {1}'s jobs".format(user, grantor.id))
            except CrossAccess.DoesNotExist:
                logger.error("No CrossAccess record for {0} from {1}".format(user, grantor.id))
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
        self._command, waiting_parent_1, is_error_1 = _Step._history_map(self._command, job.job_user)
        self._command, waiting_parent_2, is_error_2 = _Step._cross_access_map(self._command, job.job_user)
        waiting_parent = waiting_parent_1.union(waiting_parent_2)
        is_error = is_error_1 | is_error_2

        for waiting_job in waiting_parent:
            if waiting_job != job.job_id:  # avoid dead lock
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

        conda_activate = ""
        if self._env is not None and self._env.ve_type != "":
            if self._env.ve_type == "conda":
                conda_activate = "conda activate " + str(self._env.value).strip()
                if self._env.activation_command is not None and self._env.activation_command != "":
                    conda_activate = str(self._env.activation_command).strip() + " && " + conda_activate
                if self._ver_check != "":
                    self._ver_check = conda_activate + " && " + self._ver_check + " && conda deactivate"

        if self.is_shell:
            body = self._strip_shell_tag(self._command)
            if conda_activate:
                self._shell_script = conda_activate + "\n" + body + "\nconda deactivate\n"
            else:
                self._shell_script = body
            self._translated_command = [self.SHELL_TAG]
        else:
            if conda_activate:
                self._command = conda_activate + " && " + self._command + " && conda deactivate"
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
        tmp_in = []
        tmp_out = []
        tmp_mem = []
        tmp_vrt_mem = []
        tmp_cpu = []
        if raw_trainings is not None and len(raw_trainings) > 0:
            for t in raw_trainings:
                tmp_in.append(float(t.input) if t.input is not None else np.nan)
                tmp_out.append(float(t.output) if t.output is not None else np.nan)
                tmp_mem.append(float(t.mem) if t.mem is not None else np.nan)
                tmp_vrt_mem.append(float(t.vrt_mem) if t.vrt_mem is not None else np.nan)
                tmp_cpu.append(float(t.cpu) if t.cpu is not None else np.nan)

        return tmp_in, tmp_out, tmp_mem, tmp_cpu, tmp_vrt_mem

    @staticmethod
    def _fit_resource_line(x, y_arr, intercept_only=False):
        """Slope/intercept/r for one resource. Constant x falls back to intercept-only."""
        y_arr = np.array(y_arr, dtype=float)
        mask = ~(np.isnan(x) | np.isnan(y_arr))
        if intercept_only or mask.sum() < 2:
            slope = 0.0
            intercept = np.nanmean(y_arr[mask]) if mask.sum() else (np.nanmean(y_arr) if len(y_arr) else np.nan)
            return slope, intercept, 0.0
        xs = x[mask]
        ys = y_arr[mask]
        if not np.isfinite(xs).all() or np.allclose(xs, xs[0]):
            return 0.0, np.nanmean(ys), 0.0
        try:
            slope, intercept, r, _p, _se = linregress(xs, ys)
        except ValueError:
            return 0.0, np.nanmean(ys), 0.0
        return slope, intercept, r

    def _regression_factory(self, save=0):
        """
        linear regression helper
        :param save:  int, 1 or 0. If save equals 1, the record will be saved to database
        :return: coefficients
        """
        coefficients = dict()
        try:
            inputs, out, mem, cpu, vrt_mem = self._load_train_frame()
            x = np.array(inputs, dtype=float)
            # o for output
            # m for memory
            # c for CPU
            # v for virtual memory
            for y, label in zip((out, mem, cpu, vrt_mem), ("o", "m", "c", "v")):
                y_arr = np.array(y, dtype=float)
                slope, intercept, r = self._fit_resource_line(x, y_arr, intercept_only=(label == "c"))
                coefficients["r_{l}".format(l=label)] = r
                if np.isnan(slope) or np.isnan(intercept):
                    coefficients["slope_{l}".format(l=label)] = 0
                    mean = np.nanmean(y_arr)
                    coefficients["intercept_{l}".format(l=label)] = mean if not np.isnan(mean) else np.nan
                else:
                    if abs(r) > 0.8:
                        coefficients["slope_{l}".format(l=label)], coefficients[
                            "intercept_{l}".format(l=label)], = slope, intercept
                    else:
                        coefficients["slope_{l}".format(l=label)] = 0
                        coefficients["intercept_{l}".format(l=label)] = np.nanmean(y_arr)

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
            return None

    def _predict_factory(self, in_size=-99999.0, training_num=0):
        """
        Predict resource needed by a certain step
        :param in_size: float, input size
        :param training_num: int, number of training records
        :return: dict, resource dict
        """
        predict_need = {'cpu': 0, 'mem': 0, 'disk': 0, 'vrt_mem': 0}
        unknown = {'cpu': None, 'mem': None, 'disk': None, 'vrt_mem': None}
        try:
            equations = Prediction.objects.filter(step_hash=self._md5_hex)

            if len(equations) >= 3 and in_size != -99999.0:
                for equation in equations:
                    a = float(equation.a)
                    b = float(equation.b)
                    t = equation.type
                    # Stored as a=intercept, b=slope. Base mode keeps intercept only.
                    value = self._linear_resource_value(intercept=a, slope=b, in_size=in_size)
                    if t == 1:
                        predict_need['disk'] = value * float(self._settings['ml']['confidence_weight_disk'])
                    elif t == 2:
                        predict_need['mem'] = value * float(self._settings['ml']['confidence_weight_mem'])
                    elif t == 3:
                        predict_need['cpu'] = value * float(self._settings['ml']['confidence_weight_cpu'])
                    elif t == 4:
                        predict_need['vrt_mem'] = value * float(
                            self._settings['ml']['confidence_weight_mem'])
            else:
                logger.info("resource training_num=%s hash=%s", training_num, self._md5_hex)
                if training_num < 1:
                    return unknown
                else:
                    if training_num < 10:
                        fitted = self._regression_factory(save=0)
                    else:
                        fitted = self._regression_factory()
                    if not fitted:
                        return unknown
                    ao, bo, am, bm, ac, bc, av, bv = fitted
                    if not self._coeff_ok(bo, ao):
                        predict_need['disk'] = None
                    else:
                        predict_need['disk'] = int(
                            self._linear_resource_value(bo, ao, in_size) * float(self._settings['ml']['confidence_weight_disk']))
                    if not self._coeff_ok(bm, am):
                        predict_need['mem'] = None
                    else:
                        predict_need['mem'] = int(
                            self._linear_resource_value(bm, am, in_size) * float(self._settings['ml']['confidence_weight_mem']))
                    if not self._coeff_ok(bc, ac):
                        predict_need['cpu'] = None
                    else:
                        predict_need['cpu'] = int(
                            self._linear_resource_value(bc, ac, in_size) * float(self._settings['ml']['confidence_weight_cpu']))
                    if not self._coeff_ok(bv, av):
                        predict_need['vrt_mem'] = None
                    else:
                        predict_need['vrt_mem'] = int(
                            self._linear_resource_value(bv, av, in_size) * float(self._settings['ml']['confidence_weight_mem']))

                    if any([pred is None for pred in predict_need.values()]):
                        return unknown
                    # in case the predicted value is negative (resources will be added to the pool)
                    if any([pred < -1 for pred in predict_need.values()]):
                        _inputs, out, mem, cpu, vrt_mem = self._load_train_frame()
                        for pred_l, trainings in zip(("disk", "mem", "cpu", "vrt_mem"), (out, mem, cpu, vrt_mem)):
                            pred = predict_need[pred_l]
                            if pred <= 0:
                                predict_need[pred_l] = np.nanmean(trainings)

        except Exception as e:
            logger.exception(e)
            return unknown
        return self._sanitize_prediction(predict_need)

    def _use_base_prediction(self):
        ml = (self._settings or {}).get("ml") or {}
        env = (self._settings or {}).get("env") or {}
        raw = str(ml.get("predict") or env.get("predict") or "linear").strip().lower()
        return raw in ("base", "b", "intercept")

    def _coeff_ok(self, intercept, slope):
        if intercept is None:
            return False
        try:
            if np.isnan(intercept):
                return False
        except TypeError:
            return False
        if self._use_base_prediction():
            return True
        if slope is None:
            return False
        try:
            return not np.isnan(slope)
        except TypeError:
            return False

    def _linear_resource_value(self, intercept, slope, in_size):
        intercept = float(intercept)
        if self._use_base_prediction():
            return intercept
        return intercept + float(slope) * float(in_size)

    @staticmethod
    def _sanitize_prediction(predict_need):
        """Clamp NaN / inf / negative forecasts to 0. Leave None (unknown) alone."""
        cleaned = dict(predict_need or {})
        for key in ("cpu", "mem", "disk", "vrt_mem"):
            if key not in cleaned:
                continue
            value = cleaned[key]
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                cleaned[key] = 0
                continue
            if np.isnan(number) or np.isinf(number) or number < 0:
                cleaned[key] = 0
            else:
                cleaned[key] = number
        return cleaned

    def _cap_prediction_to_env(self, resource_needed):
        """Keep forecasts inside configured host limits when those keys are set."""
        cleaned = dict(resource_needed or {})
        env = (self._settings or {}).get("env") or {}

        def _env_float(key):
            try:
                return float(env.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        cpu_cores = _env_float("cpu")
        if cpu_cores > 0 and cleaned.get("cpu") is not None:
            try:
                if float(cleaned["cpu"]) > cpu_cores * 100:
                    cleaned["cpu"] = cpu_cores * 95
            except (TypeError, ValueError):
                pass
        mem_budget = _env_float("memory")
        if mem_budget > 0 and cleaned.get("mem") is not None:
            try:
                if float(cleaned["mem"]) > mem_budget:
                    cleaned["mem"] = mem_budget * 0.95
            except (TypeError, ValueError):
                pass
        if mem_budget > 0 and cleaned.get("vrt_mem") is not None:
            try:
                if float(cleaned["vrt_mem"]) > mem_budget:
                    cleaned["vrt_mem"] = mem_budget * 0.95
            except (TypeError, ValueError):
                pass
        disk_budget = _env_float("disk_quota")
        if disk_budget > 0 and cleaned.get("disk") is not None:
            try:
                if float(cleaned["disk"]) > disk_budget:
                    cleaned["disk"] = disk_budget * 0.95
            except (TypeError, ValueError):
                pass
        return cleaned

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

        folder_size_before = bases.get_folder_size(job.run_folder)
        job._folder_size_before = folder_size_before
        job.output_size = folder_size_before
        # Predict from the current workspace size. The old running sum
        # (`input_size += folder_size`) made a+b*size explode on later steps
        # and stuck jobs on "waiting for resources" (required > machine total).
        if folder_size_before > 0:
            job.input_size = folder_size_before
        elif not job.input_size:
            job.input_size = 0

        resource_needed = self._predict_factory(in_size=job.input_size, training_num=training_num)
        resource_needed = self._sanitize_prediction(resource_needed)
        resource_needed = self._cap_prediction_to_env(resource_needed)

        no_new_learn = 0 if training_num < 10 else 1
        if no_new_learn == 0:
            try:
                training = Training(step_hash=self._md5_hex, input=job.input_size, lock=1)
                training.save()
                trace_id = training.id
            except Exception as e:
                logger.exception(e)
                trace_id = None
            resource_needed["trace"] = trace_id
        resource_needed["learn"] = 1 if training_num < 10 else 0

        return resource_needed
