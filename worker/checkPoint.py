#!/usb/bin/env python
from numpy import *
import numpy
from baseDriver import get_all_config
import django_initial
from ui.models import Training, Prediction

settings = get_all_config()


def fill_missing_data_with_mean(to_handle):
    """
    fill missing data with mean value
    :param to_handle: list, data with or without missing values
    :return: list, data without missing values
    """
    no_missing_data = []
    for data in to_handle:
        if data != -1:
            no_missing_data.append(data)
    if len(no_missing_data) > 0:
        mean_value = mean(no_missing_data)
        for key, value in enumerate(to_handle):
            if value == -1:
                to_handle[key] = mean_value
    return to_handle


def load_train_frame(step_hash):
    """
    load training items' frame
    :param step_hash: string, step hash
    :return:
    """
    trainings = Training.objects.filter(step=step_hash).filter(lock=0)
    tmp_x = []
    tmp_out = []
    tmp_mem = []
    tmp_cpu = []
    for training in trainings:
        tmp_x.append(training.input)
        tmp_out.append(training.output)
        tmp_mem.append(training.mem)
        tmp_cpu.append(training.cpu)
    all_x = [[1.0, float(feat)] for feat in tmp_x]
    out_y = [float(label) for label in tmp_out]
    mem_y = [float(label) for label in tmp_mem]
    cpu_y = [float(label) for label in tmp_cpu]
    mem_y = fill_missing_data_with_mean(mem_y)
    cpu_y = fill_missing_data_with_mean(cpu_y)
    return all_x, out_y, mem_y, cpu_y


def stand_regression(x_array, y_array):
    """
    regression
    :param x_array:
    :param y_array:
    :return:
    """
    x_matrix = mat(x_array)
    y_matrix = mat(y_array).T
    x_t_x = x_matrix.T * x_matrix
    if linalg.det(x_t_x) == 0.0:
        return
    ws = x_t_x.I * (x_matrix.T * y_matrix)
    return ws


def reg_single_feature(x, y):
    """
    use linear regression on single feature
    :param x: list, x
    :param y: list, y
    :return: float, a, b, r
    """
    rc = stand_regression(x, y)
    if rc is not None:
        rc = rc.getA()
        x_matrix = mat(x)
        y_matrix = mat(y)
        x_copy = x_matrix.copy()
        x_copy.sort(0)
        y_hat = x_copy * rc
        try:
            r = corrcoef(y_hat.T, y_matrix)[0][1]
        except:
            pass
        b = rc[0][0]
        a = rc[1][0]
        if abs(r) < float(settings['ml']['threshold']):
            a = 0
            try:
                b = numpy.mean(y)
                r = numpy.std(y)
            except:
                b = 0
                r = 0

        if numpy.isnan(a):
            a = numpy.float(0)
        if numpy.isnan(b):
            try:
                b = numpy.mean(y)
            except:
                b = 0
        if numpy.isnan(r):
            try:
                r = numpy.std(y)
            except:
                r = 0
        try:
            a = a.item()
        except:
            pass
        try:
            b = b.item()
        except:
            pass
        try:
            r = r.item()
        except:
            pass
    else:
        a = 0
        try:
            b = numpy.mean(y)
            r = numpy.std(y)
        except:
            b = 0
            r = 0
    return a, b, r


def record_result(step_hash, a, b, r, t):
    """
    Save regression result
    :param step_hash: string, step hash
    :param a: float, coefficient a
    :param b: float, coefficient b
    :param r: float, relative coefficient r
    :param t: int, type, disk 1, memory 2 and cpu 3
    :return: 1 for success, 0 for failure
    """
    try:
        record_obj = Prediction(step_hash=step_hash, a=a, b=b, r=r, type=t)
        record_obj.save()
        return 1
    except:
        return 0


def regression(step_hash, save=1):
    """
    linear regression helper
    :param step_hash: string, step hash
    :param save:  int, 1 or 0. If save equals 1, the record will be saved to database
    :return: coefficients
    """
    try:
        x, out, mem, cpu = load_train_frame(step_hash)
        # Output Size
        ao, bo, ro = reg_single_feature(x, out)
        ao = 0 if numpy.isnan(ao) else ao
        bo = 0 if numpy.isnan(bo) else bo
        ro = 0 if numpy.isnan(ro) else ro

        # Memory Usage
        am, bm, rm = reg_single_feature(x, mem)
        am = 0 if numpy.isnan(am) else am
        bm = 0 if numpy.isnan(bm) else bm
        rm = 0 if numpy.isnan(rm) else rm

        # CPU Usage
        ac, bc, rc = reg_single_feature(x, cpu)
        ac = 0 if numpy.isnan(ac) else ac
        bc = 0 if numpy.isnan(bc) else bc
        rc = 0 if numpy.isnan(rc) else rc

        if save:
            record_result(step_hash, ao, bo, ro, 1)
            record_result(step_hash, am, bm, rm, 2)
            record_result(step_hash, ac, bc, rc, 3)

        return ao, bo, am, bm, ac, bc
    except Exception, e:
        print e


def predict_resource_needed(step, in_size=-99999.0, training_num=0):
    """
    Predict resource needed by a certain step
    :param step: string, step hash
    :param in_size: float, input size
    :param training_num: int, number of training records
    :return: dict, resource dict
    """
    predict_need = {}
    try:
        equations = Prediction.objects.filter(step_hash=step)
        '''
        conn, cur = con_mysql()
        get_equation_sql = """SELECT `a`, `b`, `type` FROM %s WHERE `step_hash`='%s';""" \
                           % (settings['datasets']['equation'], str(step))
        cur.execute(get_equation_sql)
        equations = cur.fetchall()
        '''
        if len(equations) > 0 and in_size != -99999.0:
            for equation in equations:
                a = float(equation.a)
                b = float(equation.b)
                t = equation.type
                if t == 1:
                    predict_need['disk'] = (a * in_size + b) * float(settings['ml']['confidence_weight_disk'])
                elif t == 2:
                    predict_need['mem'] = (a * in_size + b) * float(settings['ml']['confidence_weight_mem'])
                elif t == 3:
                    predict_need['cpu'] = (a * in_size + b) * float(settings['ml']['confidence_weight_cpu'])
        else:
            if training_num < 2:
                predict_need['cpu'] = None
                predict_need['mem'] = None
                predict_need['disk'] = None
            else:
                if training_num < 10:
                    ao, bo, am, bm, ac, bc = regression(step, 0)
                else:
                    ao, bo, am, bm, ac, bc = regression(step)
                predict_need['disk'] = int((ao * in_size + bo) * float(settings['ml']['confidence_weight_disk']))
                predict_need['mem'] = int((am * in_size + bm) * float(settings['ml']['confidence_weight_mem']))
                predict_need['cpu'] = int((ac * in_size + bc) * float(settings['ml']['confidence_weight_cpu']))

    except:
        return {'cpu': None, 'mem': None, 'disk': None}
    return predict_need

if __name__ == '__main__':
    predict_resource_needed('3449cd80644bc1f05d0d7f498069a502', 26805351086, 3)