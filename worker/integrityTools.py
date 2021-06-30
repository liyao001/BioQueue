#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 5/25/20
import hashlib
import os
from configparser import ConfigParser
from .parameterParser import upload_file_map, history_map


def digest_check(file_path):
    """
    Generate hash digest for a file

    :param file_path:
    :return:
    """
    h = hashlib.blake2b()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_a_job(job_path, input_files, db):
    """
    Create snapshot for a job

    :param job_path:
    :param input_files:
    :param db:
    :return:
    """
    snapshot = ConfigParser()
    snapshot.optionxform = str
    snapshot['input'] = dict()
    snapshot['output'] = dict()
    user_dir, _ = os.path.split(job_path)
    _, user_id = os.path.split(user_dir)

    if os.path.exists(job_path):
        for f in os.listdir(job_path):
            if f == ".snapshot.ini":
                continue
            full_path = os.path.join(job_path, f)
            if os.path.isfile(full_path):
                ctime = os.path.getctime(full_path)
                mtime = os.path.getmtime(full_path)
                digest = digest_check(full_path)
                snapshot['output'][f] = "%d;%d;%s" % (ctime, mtime, digest)

        parsed_uploaded_files, _ = upload_file_map(input_files, user_dir)
        parsed_history_files, _, _ = history_map(parsed_uploaded_files, user_id, db)
        parsed_inputs = parsed_history_files.split(";")
        for input_file in parsed_inputs:
            if os.path.exists(input_file) and os.path.isfile(input_file):
                ctime = os.path.getctime(input_file)
                mtime = os.path.getmtime(input_file)
                digest = digest_check(input_file)
                snapshot['input'][input_file] = "%d;%d;%s" % (ctime, mtime, digest)

        with open(os.path.join(job_path, ".snapshot.ini"), 'w') as configfile:
            snapshot.write(configfile)
