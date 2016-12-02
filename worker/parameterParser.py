#! /usr/bin/env python


def build_special_parameter_dict(all_output):
    special_dict = {}
    for output in all_output:
        if output.find(';') != -1:
            options = output.split(';')
            options.remove('')
            for option in options:
                k, v = option.split('=')
                k.strip()
                v.strip()
                special_dict[k] = v
    return special_dict


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
        if out_item[0] in output_dict and (int(out_item[1]) - 1) < len(output_dict[int(out_item[0])]):
            par = par.replace('{Output' + out_item[0] + '-' + out_item[1] + '}',
                              output_dict[int(out_item[0])][int(out_item[1]) - 1])
    return par


def upload_file_map(par, user_folder):
    import baseDriver
    import re
    uploaded_replacement = re.compile("\\{Uploaded:(.*?)}", re.IGNORECASE | re.DOTALL)
    for uploaded_item in re.findall(uploaded_replacement, par):
        upload_file = baseDriver.build_upload_file_path(user_folder, uploaded_item)
        if upload_file is not None:
            par = par.replace('{Uploaded:' + uploaded_item + '}', upload_file)
    return par


def parameter_string_to_list(par):
    import shlex
    parameter_string = shlex.shlex(par)
    parameter_string.quotes = '"'
    parameter_string.whitespace_split = True
    parameter_string.commenters = ''
    parameters = list(parameter_string)
    return parameters
