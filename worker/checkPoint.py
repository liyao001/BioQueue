#!/usb/bin/env python
from numpy import *
import numpy
from databaseDriver import con_mysql, get_resource, update_resource
from baseDriver import get_config, get_disk_free, get_cpu_available, get_memo_usage_available
import pandas as pd


def load_train_frame(step_hash):
    try:
        conn, cur = con_mysql()
        sql = """SELECT * FROM `%s` WHERE `step`='%s';"""%(get_config("datasets", "trainStore"), step_hash)
        train_dataframe = pd.read_sql_query(sql, conn)
        train_dataframe = train_dataframe.replace('-1', numpy.nan)
        train_dataframe['in'] = train_dataframe['in'].astype('float32')
        train_dataframe['out'] = train_dataframe['out'].astype('float32')
        train_dataframe['cpu'] = train_dataframe['cpu'].astype('float32')
        train_dataframe['mem'] = train_dataframe['mem'].astype('float32')
        train_dataframe = train_dataframe.fillna(train_dataframe.mean())
        tmp_x = list(train_dataframe['in'])
        tmp_out = list(train_dataframe['out'])
        tmp_mem = list(train_dataframe['mem'])
        tmp_cpu = list(train_dataframe['cpu'])
        all_x = [[1.0, float(feat)] for feat in tmp_x]
        out_y = [float(label) for label in tmp_out]
        mem_y = [float(label) for label in tmp_mem]
        cpu_y = [float(label) for label in tmp_cpu]
        conn.close()
        return all_x, out_y, mem_y, cpu_y
    except Exception, err:
        print err
        return 0, 0, 0, 0


def stand_regression(x_array, y_array):
    x_matrix = mat(x_array)
    y_matrix = mat(y_array).T
    x_t_x = x_matrix.T*x_matrix
    if linalg.det(x_t_x) == 0.0:
        print 'singular matrix'
        return
    ws = x_t_x.I * (x_matrix.T*y_matrix)
    return ws


def reg_single_feature(x, y):
    rc = stand_regression(x, y)
    if rc is not None:
        rc = rc.getA()
        x_matrix = mat(x)
        y_matrix = mat(y)
        x_copy = x_matrix.copy()
        x_copy.sort(0)
        y_hat = x_copy * rc
        r = corrcoef(y_hat.T, y_matrix)[0][1]
        b = rc[0][0]
        a = rc[1][0]
        return a, b, r
    else:
        return 0, 0, 0


def record_result(step_hash, a, b, r, t):
    # global con, cursor
    try:
        conn, cur = con_mysql()
        sql = """INSERT INTO `%s` (`step_hash`, `a`, `b`, `r`, `type`) VALUES ('%s', %s, %s, %s, %s);"""\
              % (get_config('datasets', 'equation'), step_hash, a, b, r, t)
        cur.execute(sql)
        conn.commit()
        conn.close()
    except Exception, err:
        print err
        return 0
    return 1


def regression(step_hash):
    x, out, mem, cpu = load_train_frame(step_hash)
    # Output Size
    ao, bo, ro, io = reg_single_feature(x, out)
    record_result(step_hash, ao, bo, ro, 1)
    # Memory Usage
    am, bm, rm, im = reg_single_feature(x, mem)
    record_result(step_hash, am, bm, rm, 2)
    # CPU Usage
    ac, bc, rc, ic = reg_single_feature(x, cpu)
    record_result(step_hash, ac, bc, rc, 3)
    return ao, bo, am, bm, ac, bc


def get_training_items(step_hash):
    dyn_sql = """SELECT COUNT(*) FROM %s WHERE `step`='%s';""" % (get_config("datasets", "trainStore"), step_hash)
    try:
        conn, cur = con_mysql()
        cur.execute(dyn_sql)
        trains = cur.fetchone()
        conn.commit()
        conn.close()
        return trains[0]
    except Exception, err:
        print err
        return 0


def check_ok_to_go(job_id, step, in_size=-99999.0, training_num=0, run_path='/'):
    try:
        conn, cur = con_mysql()
        get_equation_sql = """SELECT `a`, `b`, `type` FROM %s WHERE `step_hash`='%s';""" \
                         % (get_config("datasets", "equation"), str(step))
        cur.execute(get_equation_sql)
        equations = cur.fetchall()
        if len(equations) > 0 and in_size != -99999.0:
            predict_need = {}
            cpu_max_pool, memory_max_pool, disk_max_pool = get_resource()
            cpu_max_pool = float(cpu_max_pool)
            memory_max_pool = float(memory_max_pool)
            disk_max_pool = float(disk_max_pool)
            for equation in equations:
                a = float(equation[0])
                b = float(equation[1])
                t = equation[2]
                needed = (a * in_size + b)*0.95
                if t == '1':
                    predict_need['disk'] = needed
                    if needed > get_disk_free(run_path) or needed > disk_max_pool:
                        conn.close()
                        return 0, 0, 0, 0
                elif t == '2':
                    predict_need['mem'] = needed
                    if needed > get_memo_usage_available() or needed > memory_max_pool:
                        conn.close()
                        return 0, 0, 0, 0
                elif t == '3':
                    predict_need['cpu'] = needed
                    if needed > get_cpu_available() or needed > cpu_max_pool:
                        conn.close()
                        return 0, 0, 0, 0

            print '=='+str(job_id)+'=='+str(step)+'==', 'cpu: pred', predict_need['cpu'], 'get_cpu', \
                get_cpu_available(), 'cpuPool', cpu_max_pool, 'mem: pred', predict_need['mem'], 'get_mem', \
                get_memo_usage_available(), 'memPool', memory_max_pool, 'disk: pred', predict_need['disk'],\
                'getDisk', get_disk_free(run_path), 'diskPool', disk_max_pool
            if update_resource(-1*predict_need['cpu'], -1*predict_need['mem'], -1*predict_need['disk']):
                conn.close()
                return 1, predict_need['cpu'], predict_need['mem'], predict_need['disk']
            else:
                print '=='+str(job_id)+'=='+str(step)+'==recheck reject=='
                conn.close()
                return 0, predict_need['cpu'], predict_need['mem'], predict_need['disk']
        else:
            # training_num = get_training_items(conn, cur, step)
            if training_num < 10:
                # Not ready for machine learning
                get_running_sql = """SELECT COUNT(*) FROM %s WHERE `status`>0 AND `id` != %s;""" %\
                                (get_config("datasets", "jobDb"), job_id)
                cur.execute(get_running_sql)
                running = cur.fetchone()
                conn.close()
                if running:
                    if running[0] == 0:
                        return 1, 0, 0, 0
                    else:
                        return 0, 0, 0, 0
                else:
                    return 1, 0, 0, 0
            elif training_num < 100:
                cpu_max_pool, memory_max_pool, disk_max_pool = get_resource()
                cpu_max_pool = float(cpu_max_pool)
                memory_max_pool = float(memory_max_pool)
                disk_max_pool = float(disk_max_pool)
                ao, bo, am, bm, ac, bc = regression(step)
                disk_needed = int((ao*in_size+bo)*0.9)
                memory_needed = int((am*in_size+bm)*0.9)
                cpu_needed = int((ac*in_size+bc)*0.9)
                print '=='+str(job_id)+'=='+str(step)+'==', 'cpu: pred', cpu_needed, 'get_cpu', get_cpu_available(), 'cpuPool', cpu_max_pool, 'mem: pred', memory_needed, 'get_mem', get_memo_usage_available(), 'memPool', memory_max_pool, 'disk: pred', disk_needed, 'getDisk', get_disk_free(run_path), 'diskPool', disk_max_pool
                conn.close()
                if disk_needed > get_disk_free(run_path) or disk_needed > disk_max_pool:
                    return 0, cpu_needed, memory_needed, disk_needed
                if memory_needed > get_memo_usage_available() or memory_needed > memory_max_pool:
                    return 0, cpu_needed, memory_needed, disk_needed
                if cpu_needed > get_cpu_available() or cpu_needed > cpu_max_pool:
                    return 0, cpu_needed, memory_needed, disk_needed

                if update_resource(-1*cpu_needed, -1*memory_needed, -1*disk_needed):
                    return 1, cpu_needed, memory_needed, disk_needed
                else:
                    return 0, cpu_needed, memory_needed, disk_needed
            else:
                cpu_max_pool, memory_max_pool, disk_max_pool = get_resource()
                cpu_max_pool = float(cpu_max_pool)
                memory_max_pool = float(memory_max_pool)
                disk_max_pool = float(disk_max_pool)
                ao, bo, am, bm, ac, bc = regression(step)
                disk_needed = int((ao*in_size+bo)*0.9)
                memory_needed = int((am*in_size+bm)*0.9)
                cpu_needed = int((ac*in_size+bc)*0.9)
                print '=='+str(job_id)+'=='+str(step)+'==', 'cpu: pred', cpu_needed, 'get_cpu', get_cpu_available(), 'cpuPool', cpu_max_pool, 'mem: pred', memory_needed, 'get_mem', get_memo_usage_available(), 'memPool', memory_max_pool, 'disk: pred', disk_needed, 'getDisk', get_disk_free(run_path), 'diskPool', disk_max_pool
                conn.close()
                if disk_needed > get_disk_free(run_path) or disk_needed > disk_max_pool:
                    return 0, cpu_needed, memory_needed, disk_needed
                if memory_needed > get_memo_usage_available() or memory_needed > memory_max_pool:
                    return 0, cpu_needed, memory_needed, disk_needed
                if cpu_needed > get_cpu_available() or cpu_needed > cpu_max_pool:
                    return 0, cpu_needed, memory_needed, disk_needed

                if update_resource(-1*cpu_needed, -1*memory_needed, -1*disk_needed):
                    return 1, cpu_needed, memory_needed, disk_needed
                else:
                    return 0, cpu_needed, memory_needed, disk_needed
    except Exception, err:
        print err
        return 0, 0, 0, 0
