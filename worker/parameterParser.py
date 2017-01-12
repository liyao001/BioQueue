#!/usr/bin/env python
import baseDriver


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


def reference_map():
    return ''


def special_parameter_map(par, sp_map):
    for keyword in sp_map.keys():
        par = par.replace('{' + keyword + '}', sp_map[keyword])
    return par


def last_output_map(par, new_files):
    for key, value in enumerate(new_files):
        par = par.replace('{LastOutput' + str(key) + '}', value)
    return par


def output_file_map(par, output_dict):
    import re
    output_replacement = re.compile("\\{Output(\\d+)-(\\d+)\\}", re.IGNORECASE | re.DOTALL)
    for out_item in re.findall(output_replacement, par):
        if int(out_item[0]) in output_dict and (int(out_item[1]) - 1) < len(output_dict[int(out_item[0])]):
            par = par.replace('{Output' + out_item[0] + '-' + out_item[1] + '}',
                              output_dict[int(out_item[0])][int(out_item[1]) - 1])
    return par


def upload_file_map(par, user_folder):
    import re
    import os
    filesize = 0
    uploaded_replacement = re.compile("\\{Uploaded:(.*?)}", re.IGNORECASE | re.DOTALL)
    for uploaded_item in re.findall(uploaded_replacement, par):
        upload_file = baseDriver.build_upload_file_path(user_folder, uploaded_item)
        if upload_file is not None and upload_file != '':
            par = par.replace('{Uploaded:' + uploaded_item + '}', upload_file)
            filesize += os.path.getsize(upload_file)
    return par, filesize


def input_file_map(par, ini_dict, user_folder):
    file_size = 0
    if par.find('{InitInput}') != -1:
        init_input = ''
        for key, value in enumerate(ini_dict):
            if value.find("{Uploaded:") == -1:
                file_size += baseDriver.get_remote_size_factory(value)
                init_input += value+' '
            else:
                upload_path, upload_size = upload_file_map(value, user_folder)
                file_size += upload_size
                init_input += upload_path+' '
        par = par.replace('{InitInput}', init_input)

    for key, value in enumerate(ini_dict):
        if par.find('{InputFile' + str(key) + '}') != -1:
            par = par.replace('{InputFile' + str(key) + '}', value)
            if value.find("{Uploaded:") != -1:
                file_size += baseDriver.get_remote_size_factory(value)
    par, upload_size = upload_file_map(par, user_folder)
    file_size += upload_size
    return par, file_size


def parameter_string_to_list(par):
    import shlex
    parameter_string = shlex.shlex(par)
    parameter_string.quotes = '"'
    parameter_string.whitespace_split = True
    parameter_string.commenters = ''
    parameters = list(parameter_string)
    return parameters
