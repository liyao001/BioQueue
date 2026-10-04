"""In-memory job (Task) state: workspace, outputs, step cursor."""
import logging
import os
import shutil
import threading
from configparser import ConfigParser
from copy import copy

from worker import bases
from worker.queue.input_check import build_input_check_step, non_empty_input_entries
from worker.step import _Step
from QueueDB.models import Job, _JS_RESOURCELOCK

logger = logging.getLogger("BioQueue")

class Task(object):
    # Keys used in bases.save_output_dict / load_output_dict — must stay stable on disk.
    _FILE_MAP_KEY_LAST_OUTPUT_STRING = "LAST_OUTPUT_STRING"
    _FILE_MAP_KEY_OUTPUTS = "OUTPUTS"
    _FILE_MAP_KEY_OUTPUT_DICT = "OUTPUT_DICT"
    _FILE_MAP_KEY_OUTPUT_DICT_SUFFIX = "OUTPUT_DICT_SUFFIX"
    _FILE_MAP_KEY_NEW_FILES = "NEW_FILES"
    _FILE_MAP_KEY_LAST_OUTPUT = "LAST_OUTPUT"
    _FILE_MAP_KEY_LAST_OUTPUT_SUFFIX = "LAST_OUTPUT_SUFFIX"

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

        self._previous_step = None
        self._current_step = None

        self._parameter = job_obj.parameter

        self._result = job_obj.result
        self._resume = job_obj.resume
        self._wait_for = job_obj.wait_for
        try:
            self._job_ver = int(job_obj.version)
        except (TypeError, ValueError):
            self._job_ver = -1

        # for translating protocol
        from QueueDB.protocol_template import template_input_files

        if (getattr(job_obj.protocol, "template", "") or "").strip():
            self._job_input_files = template_input_files(
                self._job_input or "", getattr(job_obj, "sample_sheet", "") or ""
            )
        else:
            self._job_input_files = (self._job_input or "").split(";")
        self._steps = self._load_steps()
        self._job_parameters = None
        self._outputs = []
        self._new_files = []
        self._output_dict = dict()
        self._output_dict_suffix = dict()
        self._last_output = []
        self._last_output_string = ""
        self._last_output_suffix = dict()
        self._step_dependency_job_ids = set()
        self._lock = threading.Lock()

        # Resume from a later step: load prior outputs whenever resume is set.
        if self._resume != 0:
            tmp_dict = bases.load_output_dict(self._job_id)
            if self._FILE_MAP_KEY_LAST_OUTPUT_STRING in tmp_dict:
                self._last_output_string = tmp_dict[self._FILE_MAP_KEY_LAST_OUTPUT_STRING]
            if self._FILE_MAP_KEY_OUTPUTS in tmp_dict:
                self._outputs = tmp_dict[self._FILE_MAP_KEY_OUTPUTS]
            if self._FILE_MAP_KEY_OUTPUT_DICT in tmp_dict:
                self._output_dict = tmp_dict[self._FILE_MAP_KEY_OUTPUT_DICT]
            if self._FILE_MAP_KEY_OUTPUT_DICT_SUFFIX in tmp_dict:
                self._output_dict_suffix = tmp_dict[self._FILE_MAP_KEY_OUTPUT_DICT_SUFFIX]
            if self._FILE_MAP_KEY_NEW_FILES in tmp_dict:
                self._new_files = tmp_dict[self._FILE_MAP_KEY_NEW_FILES]
            if self._FILE_MAP_KEY_LAST_OUTPUT in tmp_dict:
                self._last_output = tmp_dict[self._FILE_MAP_KEY_LAST_OUTPUT]
            if self._FILE_MAP_KEY_LAST_OUTPUT_SUFFIX in tmp_dict:
                self._last_output_suffix = tmp_dict[self._FILE_MAP_KEY_LAST_OUTPUT_SUFFIX]

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
        self._input_check_step = None
        if self._resume == 0 and non_empty_input_entries(self._job_input_files):
            self._input_check_step = build_input_check_step(
                settings, len(self._job_input_files)
            )

    def _load_steps(self):
        from QueueDB.protocol_template import expand_job

        expanded = expand_job(
            self._db_obj.protocol,
            self._job_input or "",
            getattr(self._db_obj, "sample_sheet", "") or "",
        )
        if expanded is None:
            return self._protocol.customize_steps_by_user_dir(
                workspace_path=self._work_dir, user_id=self._user.id
            )
        return self._protocol.materialize_expanded(expanded, self._work_dir, self._user.id)

    def __str__(self):
        return "{job_name} ({job_id})".format(job_name=self.job_name, job_id=self.job_id)

    def __repr__(self):
        return self.__str__()

    @property
    def db_obj(self):
        return self._db_obj

    @property
    def newfiles(self):
        return self._new_files

    @newfiles.setter
    def newfiles(self, value):
        self._new_files = value

    @property
    def outputs(self):
        """

        Returns
        -------
        list
            All output file paths accumulated for this job.
        """
        return self._outputs

    @property
    def output_dict(self):
        return self._output_dict

    @property
    def output_dict_suffix(self):
        return self._output_dict_suffix

    @property
    def last_output(self):
        return self._last_output

    @last_output.setter
    def last_output(self, value):
        self._last_output = list(value) if value is not None else []

    @property
    def last_output_string(self):
        return self._last_output_string

    @last_output_string.setter
    def last_output_string(self, value):
        self._last_output_string = value

    @property
    def last_output_suffix(self):
        return self._last_output_suffix

    @last_output_suffix.setter
    def last_output_suffix(self, value):
        self._last_output_suffix = value

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
    def input_check_step(self):
        """Synthetic first-step check; not in :attr:`steps` and does not consume resume."""
        return self._input_check_step

    @property
    def user_options(self):
        return self._job_parameters

    @property
    def work_dir(self):
        return self._work_dir

    @property
    def prev_step(self):
        """Deprecated: use :attr:`_previous_step` (reserved for future step chaining)."""
        return self._previous_step

    @property
    def current_step(self):
        """Deprecated: use :attr:`_current_step` (reserved for future step chaining)."""
        return self._current_step

    @property
    def file_map(self):
        return {
            self._FILE_MAP_KEY_LAST_OUTPUT_STRING: self._last_output_string,
            self._FILE_MAP_KEY_OUTPUTS: self._outputs,
            self._FILE_MAP_KEY_OUTPUT_DICT: self._output_dict,
            self._FILE_MAP_KEY_OUTPUT_DICT_SUFFIX: self._output_dict_suffix,
            self._FILE_MAP_KEY_NEW_FILES: self._new_files,
            self._FILE_MAP_KEY_LAST_OUTPUT: self._last_output,
            self._FILE_MAP_KEY_LAST_OUTPUT_SUFFIX: self._last_output_suffix,
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

    @property
    def job_ver(self):
        return self._job_ver

    @job_ver.setter
    def job_ver(self, ver):
        try:
            self._job_ver = int(ver)
        except (TypeError, ValueError):
            self._job_ver = -1
        self._db_obj.version = self._job_ver

    def prepare_workspace(self):
        """
        Build path info for the execution of a job
        :return: tuple, path to user folder and job folder
        """
        user_folder = os.path.join(self._work_dir, str(self._user.id))
        if self._result is None or self._resume == 0:
            self.job_ver = self.job_ver + 1
            result_store = "{0}v{1}".format(self.job_id, self.job_ver)
            run_folder = os.path.join(user_folder, result_store)
            try:
                if not os.path.exists(user_folder):
                    os.mkdir(user_folder)
                if not os.path.exists(run_folder):
                    os.mkdir(run_folder)
                if self._result not in (None, "", result_store):
                    old_dir = os.path.join(user_folder, self._result)
                    if os.path.isdir(old_dir) and os.path.abspath(old_dir) != os.path.abspath(user_folder):
                        shutil.rmtree(old_dir)
                self._result = result_store
                self.db_obj.set_result(result_store)
            except Exception as e:
                logger.exception(e)
        else:
            result_store = self._result
            run_folder = os.path.join(user_folder, result_store)
            if not os.path.exists(run_folder):
                try:
                    if not os.path.exists(user_folder):
                        os.mkdir(user_folder)
                    os.mkdir(run_folder)
                except Exception as e:
                    logger.exception(e)

        self._user_folder = user_folder
        self._run_folder = run_folder
        self._result_store = result_store
        self.init_snapshot()
        return user_folder, run_folder, result_store

    @staticmethod
    def build_special_parameter_dict(all_output):
        special_dict = {}
        text = (all_output or "").strip()
        if not text:
            return special_dict
        for option in text.split(';'):
            option = option.strip()
            if not option or '=' not in option:
                continue
            k, v = option.split('=', 1)
            k = k.strip()
            v = v.strip()
            if k:
                special_dict[k] = v
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
        new_files = sorted(list(set(this_output).difference(set(self.last_output))))
        self.newfiles = [
            path if os.path.isabs(path) else os.path.join(self.run_folder, path)
            for path in new_files
        ]
        self.outputs.extend(self.newfiles)

        suffix_dict = self.build_suffix_dict(self.newfiles)
        self.output_dict[self.resume] = self.newfiles
        self.output_dict_suffix[self.resume] = suffix_dict
        self.last_output_suffix = suffix_dict
        self.last_output_string = " ".join(self.newfiles)
        self.last_output = this_output
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

            with open(expected_file, 'w') as configfile:
                snapshot.write(configfile)
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

            with open(os.path.join(self.run_folder, ".snapshot.ini"), 'w') as configfile:
                snapshot.write(configfile)
