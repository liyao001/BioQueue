#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 5/25/20
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.urls import reverse
from django.shortcuts import render, redirect
from django.template import loader
from django.http import HttpResponseRedirect, FileResponse, HttpResponse
from django.db.models import Q
from ..tools import error, success, delete_file, os_to_int, page_info
from worker.bases import get_config, get_disk_free, get_disk_used, set_config, get_bioqueue_version
from ..forms import *
from QueueDB.models import Job, ProtocolList, Step, Prediction, Reference, VirtualEnvironment, Experiment, Sample, \
    FileArchive, Workspace  #, GoogleDriveConnection
import os
import re
import base64
from urllib.parse import unquote
from urllib.request import urlopen, Request
from .Protocol import query_protocol_atom


class SharedSimpleViews:
    error_flag = 0
    supported_models = ("Experiment", "Sample", "Environment", "Workspace", "Reference", "Profile")
    internal_names = ("Experiment", "Sample", "VirtualEnvironment", "Workspace", "Reference", "Profile")
    models = (Experiment, Sample, VirtualEnvironment, Workspace, Reference, Profile)
    create_forms = (None, None, CreateVEForm, CreateWorkspaceForm, CreateReferenceForm, None)
    update_forms = (None, None, CreateVEForm, CreateWorkspaceForm, CreateReferenceForm, UpdateUserFoldersForm)
    update_action = ("redirect", "redirect", "redirect", "redirect", "redirect", "msg", )
    helper_msgs = (
        "",
        "",
        """BioQueue supports running steps in environments created by <a href="https://docs.python.org/3/library/venv.html" target="_blank"><code>venv</code></a> and <a href="https://docs.conda.io/en/latest/" target="_blank"><code>conda</code></a>. You can configure environments for steps to use in this page.""",
        "BioQueue supports putting jobs into different workspaces to make them more manageable.",
        "Specific files are likely to be used in multiple protocols (like gene annotation files, genome sequences files). To avoid the cumbersome typing of the entire path repeatedly, BioQueue allows users to create a dictionary of aliases (references) of these files so that you can refer to them with ease. ",
        ""
    )

    def __init__(self, request, model):
        if model not in self.supported_models:
            self.error_flag = 1
        if not self.error_flag:
            self.request = request
            self.model_name = model
            self.order_i = self.supported_models.index(self.model_name)
            self.model = self.models[self.order_i]

    def create(self):
        if self.request.method == "POST":
            form = self.create_forms[self.order_i](self.request.POST, request=self.request)
            if form.is_valid():
                if self.request.user.has_perm("QueueDB.add_%s" % self.internal_names[self.order_i].lower()):
                    td = form.save(commit=False)
                    if self.request.user.is_staff:
                        u = None
                    else:
                        u = self.request.user.queuedb_profile_related.delegate
                    td.user = u
                    td.save()
                    return success("%s created successfully." % self.model_name)
                else:
                    return success("Permission denied.")
            else:
                return error(form.errors)
        else:
            return render(self.request, "ui/create_simple_models.html",
                          {"form": self.create_forms[self.order_i](),
                           "model_name": self.model_name,
                           "page_help": self.helper_msgs[self.order_i],
                           "model_name_lower": self.model_name.lower()})

    def delete(self):
        try:
            form = GenericDeleteForm(self.request.GET)
            if form.is_valid():
                # make sure current user has the permission to delete records
                if self.request.user.has_perm("QueueDB.delete_%s" % self.internal_names[self.order_i].lower()):
                    try:
                        target = self.model.objects.get(id=form.cleaned_data["id"])

                        if target.check_owner(self.request.user.queuedb_profile_related.delegate, read_only=False):
                            target.delete()
                            return success("%s deleted successfully." % self.model_name)
                        else:
                            return error("You are not the owner of the record")
                    except Exception as e:
                        return error(e)
                else:
                    return error("Permission denied.")
            else:
                return error(form.errors)
        except self.model.DoesNotExist:
            return error("Record doesn't exist.")

    def update(self):
        if self.request.method == "GET":
            form = GenericDeleteForm(self.request.GET)
            if form.is_valid():
                instance = self.model.objects.get(id=form.cleaned_data["id"])
                form = self.update_forms[self.order_i](instance=instance)
                template = loader.get_template("ui/update_simple_models.html")
                context = {
                    "form": form,
                    "qid": instance.pk,
                    "action": reverse("ui:manage_simple_models", args=("update", self.model_name))
                }
                return success(template.render(context, self.request))
        elif self.request.method == "POST":
            if self.request.user.has_perm("QueueDB.change_%s" % self.internal_names[self.order_i].lower()):
                if "qid" in self.request.POST:
                    try:
                        instance = self.model.objects.get(id=int(self.request.POST["qid"]))
                        form = self.update_forms[self.order_i](self.request.POST, instance=instance, request=self.request)
                        if form.is_valid():
                            # make sure current user has the permission to delete records
                            if instance.check_owner(self.request.user.queuedb_profile_related.delegate,
                                                    read_only=False):
                                form.save()
                                if self.update_action[self.order_i] == "redirect":
                                    return redirect("ui:manage_simple_models", operation="view", model=self.model_name)
                                else:
                                    return success("%s updated successfully." % self.model_name)
                            else:
                                return error("You are not the owner of the record")
                    except Exception as e:
                        return error(e)
                else:
                    return error("Missing required field (qid)")
            else:
                return error("Permission denied.")

    def view(self):
        if self.request.user.is_superuser:
            object_list = self.model.objects.all().order_by("-pk")
        else:
            object_list = self.model.objects.filter(
                Q(user=self.request.user.queuedb_profile_related.delegate) | Q(user=None)).all().order_by("-pk")

        paginator = Paginator(object_list, 12)

        page = self.request.GET.get("page")
        objs = page_info(paginator, page)

        return render(self.request, "ui/show_%s.html" % self.model_name.lower(), {"objects": objs,
                                                                                  "page_help": self.helper_msgs[self.order_i]})


@login_required
def manage_simple_models(request, operation, model):
    """
    A unified handler function for all simple models

    Parameters
    ----------
    request :
    operation : str
        Currently supported operations: create, delete
    model : str
        Currently supported models:

    Returns
    -------

    """
    generic_c = SharedSimpleViews(request, model)
    if generic_c.error_flag:
        return render(request, "ui/error.html", {"error_msg": "Unsupported model"})
    if request.method == "POST":
        if operation == "create":
            return generic_c.create()
        elif operation == "update":
            return generic_c.update()
        else:
            return render(request, "ui/error.html", {"error_msg": "Unsupported method"})
    else:
        if operation == "view":
            return generic_c.view()
        elif operation == "delete":
            return generic_c.delete()
        elif operation == "update":
            return generic_c.update()
        else:
            return generic_c.create()


@login_required
def create_reference_shortcut(request):
    reference_form = CreateReferenceForm(request.POST)
    if reference_form.is_valid():
        cd = reference_form.cleaned_data
        if cd['source'] == 'upload' or cd['source'] == 'job':
            file_path = os.path.join(get_config('env', 'workspace'), str(request.user.queuedb_profile_related.delegate.id),
                                     base64.b64decode(cd['path']))
            ref = Reference(
                name=cd['name'],
                path=file_path,
                description=cd['description'],
                user=request.user.queuedb_profile_related.delegate,
            )
            ref.save()
            return success(ref.id)
    else:
        return error(str(reference_form.errors))


@login_required
@permission_required("QueueDB.delete_sample", raise_exception=True)
def delete_sample(request, f):
    if request.method == 'GET':
        try:
            sample = Sample.objects.get(file_path=f, user_id=request.user.queuedb_profile_related.delegate.id)
            if sample.check_owner(request.user.queuedb_profile_related.delegate, read_only=False):
                sample.delete()
                return success('Your step has been deleted.')
            else:
                return error('You are not owner of the step.')
        except Exception as e:
            return error(e)
    else:
        return error('Method error.')


@login_required
@permission_required("QueueDB.delete_sample", raise_exception=True)
def delete_upload_file(request, f):
    file_path = os.path.join(get_config('env', 'workspace'), str(request.user.queuedb_profile_related.delegate.id),
                             base64.b64decode(f).decode())
    delete_file(file_path)
    fm_path = os.path.join(get_config('env', 'workspace'), "file_comment", f)
    if os.path.exists(fm_path):
        delete_file(fm_path)

    return success('Deleted')


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
def download_file(request, job_id, f):
    try:
        if job_id != 0:
            job = Job.objects.get(id=job_id)
            file_path = os.path.join(job.run_dir,
                                     str(request.user.queuedb_profile_related.delegate.id),
                                     base64.b64decode(f.replace('f/', '').encode()).decode())
        else:
            file_path = os.path.join(get_config("env", "workspace"), str(request.user.queuedb_profile_related.id),
                                     base64.b64decode(f.replace('f/', '').encode()).decode())
        if os.path.exists(file_path):
            return download(file_path)
        else:
            return render(request, "ui/error.html", {"error_msg": "Cannot locate the file"})
    except Exception as e:
        return render(request, "ui/error.html", {"error_msg": str(e)})


def download(file_path):
    try:
        response = FileResponse(open(file_path, 'rb'))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="{0}"'.format(os.path.basename(file_path))
        response['Content-Length'] = os.path.getsize(file_path)
        return response
    except Exception as e:
        return error(e)


@login_required
def file_support(request):
    if request.method == "GET":
        fs_form = FileSupportForm(request.GET)
        if fs_form.is_valid():
            cd = fs_form.cleaned_data
            real_file = base64.b64decode(cd["file"]).decode()
            _, ext = os.path.splitext(real_file)
            from ..tools import get_maintenance_protocols
            protocol_name = "%s (%s, %s)" % (cd["support"], cd["exp"], ext)
            try:
                protocol_record = ProtocolList.objects.get(name=protocol_name, user_id=request.user.queuedb_profile_related.delegate.id)
            except ProtocolList.DoesNotExist:
                # build protocol
                if request.user.queuedb_profile_related.delegate.id == 0:
                    return error("Log in first.")
                protocol_parent = ProtocolList(name=protocol_name, user_id=request.user.queuedb_profile_related.delegate.id)
                protocol_parent.save()
                steps = list()
                maintenance_protocols = get_maintenance_protocols()
                step_order = 1
                if cd["support"] == "gg":
                    if ext != ".gz":
                        model = __import__("ui.maintenance_protocols.compress", fromlist=["gzip"])
                    else:
                        model = __import__("ui.maintenance_protocols.decompress", fromlist=["gunzip"])
                else:
                    if cd["support"] in maintenance_protocols:
                        model = __import__("ui.maintenance_protocols." + cd["support"], fromlist=[cd["support"]])
                    else:
                        return error("No support found.")
                step_order, sub_steps = model.get_sub_protocol(Step, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)

                try:
                    Step.objects.bulk_create(steps)
                    protocol_record = protocol_parent
                except:
                    protocol_parent.delete()
                    return error('Fail to save the protocol.')
            job = Job(
                protocol_id=protocol_record.id,
                parameter=';',
                run_dir=get_config('env', 'workspace'),
                user=request.user.queuedb_profile_related.delegate,
                input_file="{{Uploaded:%s}}" % real_file,
                job_name="%s-%s" % (cd['support'], real_file),
            )
            try:
                job.save()
                return success('Push the task into job queue.')
            except:
                return error('Fail to save the job.')
        else:
            return error(str(fs_form.errors))


@login_required
def fetch_data(request):
    if request.method == "POST":
        from ..tools import get_maintenance_protocols
        protocol_name = "Fetch Data From EBI ENA"
        try:
            protocol_record = ProtocolList.objects.get(name=protocol_name, user_id=0)
        except ProtocolList.DoesNotExist:
            # build protocol
            protocol_parent = ProtocolList(name=protocol_name, user_id=0)
            protocol_parent.save()
            steps = list()
            maintenance_protocols = get_maintenance_protocols()
            # download
            step_order = 1
            if "download" not in maintenance_protocols:
                protocol_parent.delete()
                return error("No protocol to fetch the data")
            else:
                model = __import__("ui.maintenance_protocols.download", fromlist=["download"])
                step_order, sub_steps = model.get_sub_protocol(Step, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)
            # decompress
            if "gunzip" not in maintenance_protocols:
                protocol_parent.delete()
                return error("No protocol to decompress (gz) the data")
            else:
                model = __import__("ui.maintenance_protocols.gunzip", fromlist=["gunzip"])
                step_order, sub_steps = model.get_sub_protocol(Step, protocol_parent, step_order)
                for sub_step in sub_steps:
                    steps.append(sub_step)
            # move to user's uploads folder
            steps.append(Step(software="mv",
                                  parameter="{{LastOutput}} {{UserUploads}}",
                                  parent=protocol_parent,
                                  user_id=0,
                                  hash='c5f8bf22aff4c9fd06eb0844e6823d5f',
                                  step_order=step_order))
            try:
                Step.objects.bulk_create(steps)
                protocol_record = protocol_parent
            except:
                protocol_parent.delete()
                return error('Fail to save the protocol.')
        user_upload_dir = os.path.join(
            os.path.join(get_config('env', 'workspace'), str(request.user.queuedb_profile_related.delegate.id)), 'uploads')
        if not os.path.exists(user_upload_dir):
            try:
                os.makedirs(user_upload_dir)
            except:
                return error('Fail to create your uploads folder')
        from ..ena import query_download_link_from_ebi
        links = query_download_link_from_ebi(request.POST["acc"])
        if len(links) > 0:
            job = Job(
                job_name=request.POST["acc"],
                protocol_id=protocol_record.id,
                parameter='UserUploads=%s;' % user_upload_dir,
                run_dir=get_config('env', 'workspace'),
                user=request.user.queuedb_profile_related.delegate,
                input_file=";".join(links),
            )
            try:
                job.save()
                return success("<br>".join(links))
            except:
                return error('Fail to save the job.')
        else:
            return error("No result found.")
    else:
        return render(request, 'ui/fetch_data.html')


@login_required
def fetch_learning(request):
    import json
    query_string = request.GET['hash'] + ',' + request.GET['type'] + ',' + str(get_config('env', 'cpu')) \
                   + ',' + str(get_config('env', 'memory')) + ',' + str(os_to_int())
    api_bus = get_config('program', 'api', 1) + '/Index/share/q/' + query_string
    try:
        res_data = urlopen(Request(api_bus, headers={"User-Agent": "BioQueue-client"})).read()
        res = json.loads(res_data.read())
        session_dict = {'hash': request.GET['hash'],
                        'type': request.GET['type'],
                        'a': res['a'],
                        'b': res['b'],
                        'r': res['r'], }
        request.session['learning'] = session_dict
        template = loader.get_template('ui/fetch_learning.html')
        context = {
            'step': res,
        }
        return success(template.render(context))
    except Exception as e:
        return error(api_bus)


@login_required
def get_learning_result(request):
    if request.method == "GET":
        learning_form = QueryLearningForm(request.GET)
        if learning_form.is_valid():
            cd = learning_form.cleaned_data
            try:
                prior = Step.objects.filter(Q(user=request.user.queuedb_profile_related.delegate)|Q(user=None),
                                            hash=cd["stephash"])
                share_rec = None
                users_rec = None
                if len(prior) > 1: # multiple priors (including from others)
                    for p in prior:
                        if p.user is None:
                            share_rec = p
                        elif p.user == request.user.queuedb_profile_related.delegate:
                            users_rec = p
                prior_rec = None
                if users_rec is not None:
                    prior_rec = users_rec
                elif share_rec is not None:
                    prior_rec = share_rec
                else:
                    prior_rec = prior[0] if len(prior) > 0 else None
                train = Prediction.objects.filter(step_hash=cd["stephash"])
                template = loader.get_template("ui/get_learning_result.html")
                context = {
                    "prior": prior_rec,
                    "hits": train
                }
                return success(template.render(context, request=request))
            except Exception as e:
                return error(e)
        else:
            return error(str(learning_form.errors))
    else:
        return error("Error Method.")


@staff_member_required
def import_learning(request):
    if request.session['learning']:
        if request.session['learning']['a'] != 'no records':
            learn = Prediction(step_hash=request.session['learning']['hash'],
                               type=request.session['learning']['type'],
                               a=request.session['learning']['a'],
                               b=request.session['learning']['b'],
                               r=request.session['learning']['r'], )
            learn.save()
            return success('Imported.')
        else:
            return error('Can not import records!')
    else:
        return error('Error')


@login_required
def index(request):
    if request.user.is_superuser:
        running_job = Job.objects.filter(status__gt=0).count()
    else:
        running_job = Job.objects.filter(user=request.user.queuedb_profile_related.delegate).filter(status__gt=0).count()

    context = {"running_jobs": running_job,
               "uid": request.user.queuedb_profile_related.delegate.id,
               "pid": request.user.queuedb_profile_related.delegate.queuedb_profile_related.id,
               "change_folder_form": UpdateUserFoldersForm(instance=request.user.queuedb_profile_related.delegate.queuedb_profile_related)}

    return render(request, "ui/index.html", context)


@login_required
def query_usage(request):
    """
    This function should only be called when the user is using IE8 or IE9
    :param request:
    :return:
    """
    api_bus = get_config('program', 'api', 1) + '/Kb/findSoftwareUsage?software=' + request.POST['software']
    try:
        req = Request(api_bus, headers={"User-Agent": "BioQueue-client"})
        res = urlopen(req).read()
        return HttpResponse(res.decode("utf-8"))
    except Exception as e:
        return error(api_bus)


@staff_member_required
def settings(request):
    if request.method == 'POST':
        set_config('env', 'workspace', request.POST['path'])
        set_config('env', 'cpu', request.POST['cpu'])
        set_config('env', 'cpu_m', request.POST['cpu_m'])
        set_config('env', 'memory', request.POST['mem'])
        set_config('env', 'disk_quota', request.POST['dquota'])
        set_config('ml', 'confidence_weight_disk', request.POST['dcw'])
        set_config('ml', 'confidence_weight_mem', request.POST['mcw'])
        set_config('ml', 'confidence_weight_cpu', request.POST['ccw'])
        set_config('ml', 'threshold', request.POST['ccthr'])

        if request.POST['mailhost'] != '':
            set_config('mail', 'notify', 'on')
            set_config('mail', 'mail_host', request.POST['mailhost'])
            set_config('mail', 'mail_port', request.POST['mailport'])
            set_config('mail', 'mail_user', request.POST['mailuser'])
            set_config('mail', 'mail_password', request.POST['mailpassword'])
            if request.POST['protocol'] == 'ssl':
                set_config('mail', 'ssl', 'true')
            elif request.POST['protocol'] == 'tls':
                set_config('mail', 'tls', 'true')
        else:
            set_config('mail', 'notify', 'off')

        if request.POST['cluster_type'] != '':
            set_config('cluster', 'type', request.POST['cluster_type'])
            set_config('cluster', 'cpu', request.POST['job_cpu'])
            set_config('cluster', 'queue', request.POST['job_dest'])
            set_config('cluster', 'mem', request.POST['job_mem'])
            set_config('cluster', 'vrt', request.POST['job_vrt'])
            set_config('cluster', 'walltime', request.POST['job_wt'])
        else:
            set_config('cluster', 'type', '')
            set_config('cluster', 'cpu', '')
            set_config('cluster', 'queue', '')
            set_config('cluster', 'mem', '')
            set_config('cluster', 'vrt', '')
            set_config('cluster', 'walltime', '')

        return HttpResponseRedirect('/ui/settings')
    else:
        from worker.cluster_support import get_cluster_models
        try:
            if get_config('mail', 'ssl') == 'true':
                mail_protocol = 'ssl'
            elif get_config('mail', 'tls') == 'true':
                mail_protocol = 'tls'
            else:
                mail_protocol = 'nm'

            configuration = {
                'run_folder': get_config('env', 'workspace'),
                'cpu': get_config('env', 'cpu'),
                'cpu_m': get_config('env', 'cpu_m'),
                'memory': get_config('env', 'memory'),
                'disk_quota': get_config('env', 'disk_quota'),
                'threshold': get_config('ml', 'threshold'),
                'disk_confidence_weight': get_config('ml', 'confidence_weight_disk'),
                'mem_confidence_weight': get_config('ml', 'confidence_weight_mem'),
                'cpu_confidence_weight': get_config('ml', 'confidence_weight_cpu'),
                'max_disk': round((get_disk_free(get_config('env', 'workspace'))
                                   + get_disk_used(get_config('env', 'workspace'))) / 1073741824),
                'free_disk': round(get_disk_free(get_config('env', 'workspace')) / 1073741824),
                'mail_host': get_config('mail', 'mail_host'),
                'mail_port': get_config('mail', 'mail_port'),
                'mail_user': get_config('mail', 'mail_user'),
                'mail_password': get_config('mail', 'mail_password'),
                'mail_protocol': mail_protocol,
                'cluster_models': get_cluster_models(),
                'cluster_type': get_config('cluster', 'type'),
                'job_cpu': get_config('cluster', 'cpu'),
                'job_dest': get_config('cluster', 'queue'),
                'job_mem': get_config('cluster', 'mem'),
                'job_vrt': get_config('cluster', 'vrt'),
                'job_wt': get_config('cluster', 'walltime'),
                'rv': get_config('program', 'latest_version', 1),
                'cv': get_bioqueue_version(),
            }
        except Exception as e:
            return render(request, 'ui/error.html', {'error_msg': e})

        return render(request, 'ui/settings.html', configuration)


@login_required
@permission_required("QueueDB.add_workspace", raise_exception=True)
def set_workspace(request):
    if request.method == 'POST':
        sw_form = SetWorkspaceForm(request.POST)
        if sw_form.is_valid():
            cd = sw_form.cleaned_data
            if cd["ws"] == -1:
                request.session["workspace"] = None
                return success("Redirecting...(all)")
            try:
                ws = Workspace.objects.get(id=cd["ws"], user=request.user.queuedb_profile_related.delegate)
                request.session["workspace"] = ws.id
                return success("Redirecting...")
            except:
                request.session["workspace"] = None
                return success("Redirecting...")
        else:
            return error(sw_form.errors)
    else:
        return error("Wrong method")


@login_required
def show_learning(request):
    protocols = query_protocol_atom(request.user.is_staff, request.user.queuedb_profile_related.delegate,
                                    request.GET.get('page'))
    return render(request, 'ui/show_learning.html', {'protocol_list': protocols})


@login_required
def show_learning_steps(request):
    if request.method == 'GET':
        if 'parent' in request.GET:
            if request.user.is_superuser:
                step_list = Step.objects.filter(parent=int(request.GET['parent'])).all()
            else:
                step_list = Step.objects.filter(parent=
                                                    int(request.GET['parent'])).filter(
                    user=request.user.queuedb_profile_related.delegate).all()
            template = loader.get_template('ui/show_learning_steps.html')
            context = {
                'step_list': step_list,
            }
            return success(template.render(context))
        else:
            return error('Wrong parameter.')
    else:
        return error('Method error.')


@login_required
@permission_required("QueueDB.view_job", raise_exception=True)
@permission_required("QueueDB.add_filearchive", raise_exception=True)
def tar_files(request):
    if request.method == "POST":
        tar_form = TarFilesForm(request.POST)
        if tar_form.is_valid():
            cd = tar_form.cleaned_data
            files = cd["input_files"].split(";")
            job_id = -1
            job_obj = None
            protocol_id = -1
            data_dict = {
                "protocol": "",
                "protocol_ver": "",
                "input_files": "",
                "files_to_arv": [],
                "file_id_remote": "ph",
                "job": None,
                "raw_files": "ph",
            }

            _j_cache = dict()
            for file in files:
                history_replacement = re.compile("\\{\\{History:(\\d+)-(.*?)\\}\\}", re.IGNORECASE | re.DOTALL)
                for history_item in re.findall(history_replacement, file):
                    history_id = int(history_item[0])
                    if job_id == -1:
                        job_id = history_id
                        if job_id not in _j_cache:
                            _j_cache[job_id] = Job.objects.get(id=int(job_id))
                        job_obj = _j_cache[job_id]
                        protocol_id = job_obj.protocol.id
                        data_dict["protocol"] = "%s (%d)" % (job_obj.protocol.name, protocol_id)
                        data_dict["protocol_ver"] = job_obj.protocol_ver
                        data_dict["input_files"] = job_obj.input_file

                    elif job_id != history_id:
                        return error("Only files from the same job can be archived.")

                    history_file = history_item[1]
                    try:
                        history_record = _j_cache[history_id]
                        if int(history_record.user) == request.user.queuedb_profile_related.delegated or request.user.is_staff:
                            history_rep = os.path.join(history_record.run_dir,
                                                       str(history_record.user.queuedb_profile_related.delegate.id),
                                                       history_record.result)
                            history_rep = os.path.join(history_rep, history_file)
                            data_dict["files_to_arv"].append(history_rep)
                        else:
                            return error("Permission denied.")
                    except Exception as e:
                        return error(e)
            data_dict["job"] = job_obj
            data_dict["raw_files"] = cd["input_files"]
            try:
                fa = FileArchive(
                    protocol=ProtocolList.objects.get(id=protocol_id),
                    protocol_ver=data_dict["protocol_ver"],
                    inputs=data_dict["input_files"],
                    files=data_dict["files_to_arv"],
                    file_md5s="ph",
                    shared_with=cd["shared_with"],
                    archive_file="ph",
                    user=request.user.queuedb_profile_related.delegate,
                    description=cd["description"],
                    job=data_dict["job"],
                    raw_files=data_dict["raw_files"],
                )
                fa.save()
            except Exception as e:
                return error(e)
            return success("Task in queue, please check out later.")
        else:
            return error(tar_form.errors)
    else:
        need_connection = 0
        # try:
        #     plugin_connection = GoogleDriveConnection.objects.get(user=request.user.queuedb_profile_related.delegate)
        # except GoogleDriveConnection.DoesNotExist:
        #     need_connection = 1
        if request.user.is_staff:
            rxvs = FileArchive.objects.all().order_by("-create_time")
        else:
            rxvs = FileArchive.objects.filter(user=request.user.queuedb_profile_related.delegate).order_by("-create_time")
        paginator = Paginator(rxvs, 5)
        list_flag = 0

        if request.GET.get("page") is not None:
            list_flag = 1

        return render(request, "ui/tar_files.html",
                      {"connect_tag": need_connection, "rxvs": page_info(paginator, request.GET.get("page")),
                       "lf": list_flag})
