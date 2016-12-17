#!/usr/bin/env python
from databaseDriver import con_mysql, update_resource
import subprocess
import checkPoint
import HTMLParser
import time
import os
import baseDriver

# con, cursor = con_mysql()
this_input_size = 0
this_output_size = 0
cumulative_output_size = 0
trace_id = 0
ini_file = ''
root_path = os.path.split(os.path.realpath(__file__))[0]
settings = baseDriver.get_all_config()


def get_protocol(process_id):
    """Get entire protocol and assign those constants"""
    try:
        con, cursor = con_mysql()
        html_parser = HTMLParser.HTMLParser()
        query = '''SELECT software, parameter, hash FROM %s WHERE `parent`=%s ORDER BY id ASC;''' \
                % (settings['datasets']['protocol_db'], process_id)
        cursor.execute(query)
        tmp = cursor.fetchall()
        steps = [html_parser.unescape(str(step[0]).rstrip() + " " + str(step[1])) for step in tmp]
        hashes = [str(step[2]) for step in tmp]
        parse_protocol_cst(steps)
        con.close()
        return steps, hashes
    except Exception, e:
        print e
        return


def parse_protocol_cst(steps):
    """Replace constants in step"""
    from multiprocessing import cpu_count
    constant = {
        '{ThreadN}': cpu_count(),
    }

    for k, v in enumerate(steps):
        for key in constant.keys():
            if v.find(key) != -1:
                steps[k] = steps[k].replace(key, str(constant[key]))


def get_job():
    """Get job information from queue database"""
    '''
    dynSQL = """SELECT COUNT(*) FROM %s WHERE `status` > 0 or `status` = -2;"""%baseDriver.get_config("datasets", "job_db")
    cursor.execute(dynSQL)
    running = cursor.fetchone()
    con.commit()
    if int(running[0])!=0:
        return 0, 0, 0, 0, 0, 0, 0
    '''
    try:
        con, cursor = con_mysql()
        query = """SELECT `id`, `protocol_id`, `input_file`, `parameter`, `run_dir`, `user_id`, `resume` FROM `%s` WHERE `status` = 0 ORDER BY `id` LIMIT 1;""" \
                % settings['datasets']['job_db']
        cursor.execute(query)
        res = cursor.fetchone()

        if res is not None:
            job_id, protocol, input_file, parameter, run_directory, user, resume = res
            baseDriver.update(settings['datasets']['job_db'], job_id, 'status', -2)
            con.close()
            return job_id, protocol, input_file, parameter, run_directory, user, int(resume)
        else:
            con.close()
            return 0, 0, 0, 0, 0, 0, 0
    except Exception, e:
        print e
        return 0, 0, 0, 0, 0, 0, 0


def insert_sql(sql):
    try:
        con, cursor = con_mysql()
        cursor.execute(sql)
        row_id = cursor.insert_id()
        con.commit()
        con.close()
    except Exception, e:
        print e
        return 0
    return row_id


def call_process(parameter, step, job_id, run_directory='', step_hash='', upload_size = 0):
    global this_input_size, this_output_size, cumulative_output_size, trace_id, ini_file
    iso_file = 0
    learning = 0
    folder_size_before = 0
    try:
        training_num = get_training_items(step_hash)
        if settings['cluster']['type']:
            import clusterSupport
            baseDriver.update(settings['datasets']['job_db'], job_id, 'status', step + 1)
            return_code = clusterSupport.main(settings['cluster']['type'], ' '.join(parameter),
                                              job_id, step, settings['cluster']['cpu'],
                                              settings['cluster']['queue'], run_directory)
            return return_code
        else:
            if run_directory == '':
                print 'Please specify your workspace!'
                return 1
            if training_num < 100:
                learning = 1
            if this_input_size == 0:
                this_input_size = baseDriver.get_folder_size(run_directory)
                if this_input_size == 0 and step == 0:
                    this_input_size = baseDriver.get_remote_size_factory(ini_file)
                    iso_file = 1
            else:
                this_input_size = this_output_size
            folder_size_before = baseDriver.get_folder_size(run_directory)
            this_input_size += upload_size
            if learning == 1:
                trace_id = create_machine_learning_item(step_hash, this_input_size)
            process_maintain = subprocess.Popen(["python", os.path.join(root_path, 'procManeuver.py'),
                                                 "-p", str(os.getpid()), "-j", str(job_id)], shell=False,
                                                stdout=None, stderr=subprocess.STDOUT)
            status, cpu_needed, memory_needed, disk_needed = checkPoint.check_ok_to_go(job_id, step_hash,
                                                                                       this_input_size,
                                                                                       training_num)
            while not status:
                time.sleep(13)
                status, cpu_needed, memory_needed, disk_needed = checkPoint.check_ok_to_go(job_id,
                                                                                           step_hash,
                                                                                           this_input_size,
                                                                                           training_num)
            step_process = subprocess.Popen(parameter, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                    cwd=run_directory)
            if learning == 1 and step_hash != '':
                learn_process = subprocess.Popen(["python", os.path.join(root_path, 'mlCollector.py'),
                                                  "-p", str(step_process.pid), "-n", str(step_hash),
                                                  "-j", str(trace_id)], shell=False, stdout=None,
                                                 stderr=subprocess.STDOUT)
            baseDriver.update(settings['datasets']['job_db'], job_id, 'status', step + 1)
            stdout, stderr = step_process.communicate()
            stdout += stderr
            baseDriver.record_job(job_id, stdout)
            if run_directory != '':
                if iso_file == 1:
                    this_input_size = 0
                    iso_file = 0
                this_output_size = baseDriver.get_folder_size(run_directory) - folder_size_before
                print '==' + str(job_id) + '==' + str(step) + '== disk_needed', disk_needed, 'outputSize', this_output_size
                update_resource(float(cpu_needed), float(memory_needed), float(disk_needed) - this_output_size)
                cumulative_output_size += this_output_size
                if learning == 1:
                    baseDriver.update(settings['datasets']['train_db'], trace_id, 'output', this_output_size)
            return step_process.returncode

    except Exception, e:
        print 'Error caused by CPBQueue', e
        # baseDriver.update(baseDriver.get_config("datasets", "job_db"), job_id, 'status', -3)
        return 1


def create_machine_learning_item(step_hash, inputSize):
    dyn_sql = """INSERT INTO %s (`step`, `input`) VALUES ('%s', '%s');""" \
              % (settings['datasets']['train_db'], step_hash, str(inputSize))
    try:
        con, cursor = con_mysql()
        cursor.execute(dyn_sql)
        record_id = con.insert_id()
        con.commit()
        con.close()
    except Exception, e:
        print e
        return 0
    return record_id


def get_training_items(step_hash):
    dyn_sql = """SELECT COUNT(*) FROM %s WHERE `step`='%s';""" \
              % (settings['datasets']['train_db'], step_hash)
    try:
        con, cursor = con_mysql()
        cursor.execute(dyn_sql)
        trains = cursor.fetchone()
        con.commit()
        con.close()
        return trains[0]
    except Exception, e:
        print e
        return 0


def get_user_reference(user):
    dyn_sql = """SELECT `name`, `path` FROM %s WHERE `user_id`='%s';""" % (settings['datasets']['reference_db'], user)
    try:
        con, cursor = con_mysql()
        cursor.execute(dyn_sql)
        references = cursor.fetchall()
        reference = dict()
        for k, v in references:
            key, value = k.strip(), v.strip()
            reference[key] = value
        con.close()
        return reference
    except Exception, e:
        print e
        return 0


def create_user_folder(uf, jf):
    try:
        if not os.path.exists(uf):
            os.mkdir(uf)
        if not os.path.exists(jf):
            os.mkdir(jf)
    except Exception, e:
        print e


def dynamic_run():
    import parameterParser
    global trace_id, ini_file, cumulative_output_size
    outputs = []
    new_files = []
    out_dic = {}
    last_output_string = ''

    jid, protocol, ini_file, indeed_parameter, run_folder, user_id, resume = get_job()

    if jid == 0 or protocol == 0:
        return 1

    result_store = baseDriver.rand_sig() + str(jid)
    user_folder = os.path.join(run_folder, str(user_id))
    run_folder = os.path.join(user_folder, result_store)

    create_user_folder(user_folder, run_folder)
    baseDriver.update(settings['datasets']['job_db'], jid, 'result', result_store)

    steps, hs = get_protocol(protocol)

    so = parameterParser.build_special_parameter_dict(indeed_parameter)
    user_reference = get_user_reference(user_id)
    so = dict(so, **user_reference)

    for k, v in enumerate(steps):
        # skip finished steps
        if k < resume:
            continue
        # load cached output
        if resume != -1:
            out_dic = baseDriver.load_output_dict(jid)

        steps[k] = steps[k].replace('{InitInput}', ini_file)
        steps[k] = steps[k].replace('{Job}', str(jid))
        steps[k] = steps[k].replace('{LastOutput}', last_output_string)
        steps[k] = steps[k].replace('{AllOutputBefore}', ' '.join(outputs))
        steps[k] = steps[k].replace('{Workspace}', run_folder)
        steps[k] = parameterParser.last_output_map(steps[k], new_files)
        steps[k] = parameterParser.special_parameter_map(steps[k], so)
        steps[k] = parameterParser.output_file_map(steps[k], out_dic)
        steps[k], upload_file_size = parameterParser.upload_file_map(steps[k], user_folder)
        ini_file, upload_in_ini = parameterParser.upload_file_map(ini_file, user_folder)

        parameters = parameterParser.parameter_string_to_list(steps[k])
        #last_output = os.listdir(run_folder)
        last_output = []

        if run_folder:
            ret = call_process(parameters, k, jid,
                               run_directory=run_folder,
                               step_hash=hs[k],
                               upload_size = upload_file_size-upload_in_ini)
        else:
            ret = call_process(parameters, k, jid)

        running_set = {'resume': k, 'status': -2}
        baseDriver.multi_update(settings['datasets']['job_db'], jid, running_set)

        if ret != 0:
            print "Error when executing: " + steps[k]
            m = {'status': -3, 'ter': 0}
            baseDriver.multi_update(settings['datasets']['job_db'], jid, m)
            baseDriver.delete(settings['datasets']['train_db'], trace_id)
            baseDriver.save_output_dict(out_dic, jid)
            return 2
        this_output = os.listdir(run_folder)
        new_files = sorted(list(set(this_output).difference(set(last_output))))
        #safety
        new_files = [os.path.join(run_folder, file_name) for file_name in new_files]
        outputs.extend(new_files)
        out_dic[k + 1] = new_files
        last_output_string = ' '.join(new_files)

    final_size = baseDriver.get_folder_size(run_folder)
    update_resource(0, 0, cumulative_output_size - final_size)
    if ret == 0:
        # mark as finished
        baseDriver.update(settings['datasets']['job_db'], jid, 'status', -1)
        baseDriver.del_output_dict(jid)
    else:
        # save output
        baseDriver.save_output_dict(out_dic, jid)


if __name__ == '__main__':
    dynamic_run()
