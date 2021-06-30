#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Li Yao
# @Date: 12/01/16
from __future__ import unicode_literals
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils.translation import ugettext_lazy as _


_YES = 1
_NO = 0

_PD_DISK = 1
_PD_MEM = 2
_PD_CPU = 3
_PD_VRTMEM = 4
PREDICTION_CHOICES = (
    (_PD_DISK, 'Disk'),
    (_PD_MEM, 'Memory'),
    (_PD_CPU, 'CPU'),
    (_PD_VRTMEM, 'Virtual Memory'),
)

CHECKPOINT_CHOICES = (
    (0, 'Ok'),
    (1, 'Disk'),
    (2, 'Memory'),
    (3, 'CPU'),
    (4, 'Former'),
    (5, 'Peer'),
    (6, 'Virtual Memory')
)

YES_OR_NO = (
    (0, 'No'),
    (1, 'Yes')
)

OPERATIONS_FOR_AUDITION = (
    (0, 'Created a job'),
    (1, 'Rerun a job'),
    (2, 'Resumed a job'),
    (3, 'Finished a job'),
    (4, 'Deleted a job'),
)

_JS_WRONG = -3
_JS_RESOURCELOCK = -2
_JS_FINISHED = -1
_JS_WAITING = 0
_JS_RUNNING = 1
_JS_INTERRUPTED = 2
JOB_STATUS = (
    (_JS_WRONG, "Wrong"),
    (_JS_RESOURCELOCK, "ResourceLock"),
    (_JS_FINISHED, "Finished"),
    (_JS_WAITING, "Waiting"),
    (_JS_RUNNING, "Running"),
    (_JS_INTERRUPTED, "Interrupted"),
)


# class JobMonitor(models.Model):
#     job_id = models.ForeignKey('Queue', on_delete=models.CASCADE)
#     step_id = models.ForeignKey('Protocol', on_delete=models.CASCADE)
#     user_time = models.FloatField(default=0.)
#     system_time = models.FloatField(default=0.)
#     rss = models.IntegerField(default=0)
#     uss = models.IntegerField(default=0)
#     pss = models.IntegerField(default=0)
#
#     def __str__(self):
#         return self.job_id.job_name + " - " + self.step_id.software


class _OwnerModel(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True,
                             related_name="%(app_label)s_%(class)s_related")

    class Meta:
        abstract = True

    def check_owner(self, user, read_only=True):
        """
        Check whether the requesting user has the permission to read/change the record

        :param user: int or User
            either or int (id of the user) or a User object
        :param read_only: bool
            If the ongoing operation only requires for read permission
        :return:
        has_perm : bool
            True for having permission to access the record
        """
        if not isinstance(user, User):
            if type(user) is int:
                user = User.objects.get(id=user)
            else:
                raise AssertionError("user should be a User object or an integer")
        if self.user is None:
            if read_only:  # public
                return True
            else:
                if user.is_staff:
                    return True
                else:
                    return False
        elif int(self.user.id) == user.id:  # owner
            return True
        elif user.is_staff:  # administrators
            return True
        else:
            return False


class Audition(_OwnerModel):
    operation = models.CharField(max_length=50)
    related_job = models.ForeignKey("Job", on_delete=models.CASCADE)
    job_name = models.CharField(max_length=100)
    prev_par = models.TextField()
    new_par = models.TextField()
    prev_input = models.TextField()
    current_input = models.TextField()
    protocol = models.CharField(max_length=100)
    protocol_ver = models.CharField(max_length=100)
    resume_point = models.SmallIntegerField(default=-1)
    create_time = models.DateTimeField(auto_now_add=True)


class VirtualEnvironment(_OwnerModel):
    """Virtual Environment Table
    Save VEs which can be activated by source command
    """
    name = models.CharField(max_length=50)
    ve_type = models.CharField(choices=(("conda", "conda"),
                                        ("venv", "venv")),
                               max_length=10, default="conda")
    value = models.TextField()
    activation_command = models.TextField(null=True, blank=True)

    class Meta:
        try:
            constraints = [models.UniqueConstraint(fields=["name", "user"], name="unique_name")]
        except:
            unique_together = ("name", "user")

    def __str__(self):
        return self.name


class Prediction(models.Model):
    """Prediction Table
    Save linear model for memory, output size
    Or average, sd for CPU
    """
    step_hash = models.CharField(max_length=50, db_index=True)
    a = models.CharField(max_length=50, blank=True, null=True)
    b = models.CharField(max_length=50, blank=True, null=True)
    r = models.CharField(max_length=50, blank=True, null=True)
    create_time = models.DateTimeField(auto_now_add=True)
    type = models.SmallIntegerField(choices=PREDICTION_CHOICES)

    def __str__(self):
        return self.step_hash

    def step_name(self):
        """
        step = Protocol.objects.filter(hash=self.step_hash)
        return step[0].software+' '+step[0].parameter
        """
        steps = Step.objects.filter(hash=self.step_hash)
        step_key = None
        if steps:
            step_key = steps[0]
        if step_key:
            return step_key.software + ' ' + step_key.parameter
        else:
            return ''

    step_name.admin_order_field = 'step_hash'


class Step(_OwnerModel):
    """Protocol Table
    Save steps for protocol
    """
    software = models.CharField(max_length=50)
    parameter = models.TextField()
    specify_output = models.CharField(max_length=50, blank=True, null=True)
    parent = models.ForeignKey("ProtocolList", on_delete=models.CASCADE)
    hash = models.CharField(max_length=50)
    step_order = models.SmallIntegerField(default=1)
    env = models.ForeignKey("VirtualEnvironment", blank=True, null=True, on_delete=models.PROTECT)
    force_local = models.SmallIntegerField(default=0, choices=YES_OR_NO)
    cpu_prior = models.IntegerField(default=-1, blank=True)
    mem_prior = models.IntegerField(default=-1, blank=True)
    disk_prior = models.IntegerField(default=-1, blank=True)

    def __str__(self):
        return self.software + ' ' + self.parameter

    def check_parent(self, parent):
        if int(self.parent) == parent:
            return 1
        else:
            return 0

    def update_order(self, new_order):
        self.step_order = new_order
        return 1

    def update_parameter(self, new_parameter):
        import hashlib
        m = hashlib.md5(str(self.software + ' ' + new_parameter.strip()).encode())
        self.hash = m.hexdigest()
        self.parameter = new_parameter
        return 1


class ProtocolList(_OwnerModel):
    """Protocol List Table
    Save protocol names
    """
    name = models.CharField(max_length=500)
    description = models.TextField(null=True)
    ver = models.CharField(max_length=33, null=True)

    def __str__(self):
        return self.name


class Job(_OwnerModel):
    """Queue Table
    Save tasks
    """
    protocol = models.ForeignKey("ProtocolList", on_delete=models.CASCADE)
    protocol_ver = models.CharField(max_length=100, blank=True, null=True)
    job_name = models.CharField(max_length=100, blank=True, null=True)
    input_file = models.TextField()
    parameter = models.TextField()
    run_dir = models.TextField(blank=True, null=True)
    result = models.TextField(blank=True, null=True)
    status = models.SmallIntegerField(default=_JS_WAITING, choices=JOB_STATUS)
    update_time = models.DateTimeField(auto_now=True)
    create_time = models.DateTimeField(auto_now_add=True)
    resume = models.SmallIntegerField(default=0)
    ter = models.SmallIntegerField(default=_NO, choices=YES_OR_NO)
    audit = models.SmallIntegerField(default=_NO, choices=YES_OR_NO)
    wait_for = models.SmallIntegerField(default=0, choices=CHECKPOINT_CHOICES)
    workspace = models.ForeignKey("Workspace", blank=True, null=True, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.id)

    def terminate_job(self):
        self.ter = 1
        self.save()
        Audition(operation="Terminated",
                 related_job=self,
                 job_name=self.job_name,
                 prev_par=self.parameter,
                 new_par=self.parameter,
                 prev_input=self.input_file,
                 current_input=self.input_file,
                 protocol=self.protocol.name,
                 protocol_ver=self.protocol_ver,
                 resume_point=self.resume,
                 user=self.user).save()

    def rerun_job(self):
        self.status = 0
        self.resume = 0
        self.ter = 0
        self.protocol_ver = self.protocol.ver
        self.audit = 0
        self.save()
        Audition(operation="Reran",
                 related_job=self,
                 job_name=self.job_name,
                 prev_par=self.parameter,
                 new_par=self.parameter,
                 prev_input=self.input_file,
                 current_input=self.input_file,
                 protocol=self.protocol.name,
                 protocol_ver=self.protocol_ver,
                 resume_point=self.resume,
                 user=self.user).save()

    def resume_job(self, rollback):
        self.resume = rollback
        self.status = 0
        self.protocol_ver = self.protocol.ver
        self.audit = 0
        self.save()
        Audition(operation="Resumed",
                 related_job=self,
                 job_name=self.job_name,
                 prev_par=self.parameter,
                 new_par=self.parameter,
                 prev_input=self.input_file,
                 current_input=self.input_file,
                 protocol=self.protocol.name,
                 protocol_ver=self.protocol_ver,
                 resume_point=self.resume,
                 user=self.user).save()

    def set_done(self):
        self.status = _JS_FINISHED
        self.save()
        Audition(operation="Done",
                 related_job=self,
                 job_name=self.job_name,
                 prev_par=self.parameter,
                 new_par=self.parameter,
                 prev_input=self.input_file,
                 current_input=self.input_file,
                 protocol=self.protocol.name,
                 protocol_ver=self.protocol_ver,
                 resume_point=self.resume,
                 user=self.user).save()
        if self.user.queuedb_profile_related.notification_enabled:
            Notification(msg=self.job_name+" ("+str(self.id)+") "+"is done.", user=self.user).save()

    def set_result(self, value):
        self.result = value
        self.save()

    def set_status(self, status):
        self.status = status
        self.save()

    def set_wait(self, for_what):
        self.status = _JS_WAITING
        self.wait_for = for_what
        self.save()

    def get_result(self):
        return self.result

    def update_status(self, status):
        self.status = status
        self.save()

    def update_inputs(self, new_inputs):
        Audition(operation="Changed inputs",
                 related_job=self,
                 job_name=self.job_name,
                 prev_par=self.parameter,
                 new_par=self.parameter,
                 prev_input=self.input_file,
                 current_input=new_inputs,
                 protocol=self.protocol.name,
                 protocol_ver=self.protocol_ver,
                 resume_point=self.resume,
                 user=self.user).save()
        self.input_file = new_inputs
        self.audit = 1
        self.save()

    def update_parameter(self, new_par):
        Audition(operation="Changed parameters",
                 related_job=self,
                 job_name=self.job_name,
                 prev_par=self.parameter,
                 new_par=new_par,
                 prev_input=self.input_file,
                 current_input=self.input_file,
                 protocol=self.protocol.name,
                 protocol_ver=self.protocol_ver,
                 resume_point=self.resume,
                 user=self.user).save()
        self.parameter = new_par
        self.audit = 1
        self.save()


class Reference(_OwnerModel):
    """Reference Table
    Save custom references
    """
    name = models.CharField(max_length=255)
    path = models.CharField(max_length=500)
    description = models.TextField()

    def __str__(self):
        return self.name


class Training(models.Model):
    """Training Table
    Save training items
    """
    step_hash = models.CharField(max_length=50, db_index=True)
    input = models.CharField(max_length=50, blank=True, null=True)
    output = models.CharField(max_length=50, blank=True, null=True)
    mem = models.CharField(max_length=50, blank=True, null=True)
    vrt_mem = models.CharField(max_length=50, blank=True, null=True)
    cpu = models.CharField(max_length=50, blank=True, null=True)
    create_time = models.DateTimeField(auto_now_add=True)
    lock = models.SmallIntegerField(default=1)

    def __str__(self):
        return self.step_hash

    def step_name(self):
        steps = Step.objects.filter(hash=self.step_hash)
        step_key = None
        if steps:
            step_key = steps[0]
        if step_key:
            return step_key.software + ' ' + step_key.parameter
        else:
            return 'Step missing'

    def update_cpu_mem(self, cpu, mem, vrt_mem):
        self.mem = mem
        self.cpu = cpu
        self.vrt_mem = vrt_mem
        self.save()

    def mem_in_gb(self):
        if self.mem:
            try:
                return str(round(float(self.mem) / 1024 / 1024 / 1024, 2)) + 'GB'
            except:
                return ''
        else:
            return '-'

    def vrt_mem_in_gb(self):
        if self.vrt_mem:
            try:
                return str(round(float(self.vrt_mem) / 1024 / 1024 / 1024, 2)) + 'GB'
            except:
                return ''
        else:
            return '-'

    step_name.admin_order_field = 'step'


class Experiment(models.Model):
    name = models.CharField(max_length=300)
    required_fields = models.TextField()
    file_support = models.CharField(null=True, blank=True, max_length=500)

    def __str__(self):
        return self.name


class Profile(models.Model):
    from uuid import uuid4
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="%(app_label)s_%(class)s_related")
    delegate = models.ForeignKey(User, on_delete=models.CASCADE, related_name="%(app_label)s_delegate_related")
    api_key = models.CharField(default=uuid4, max_length=64, unique=True)
    api_secret = models.CharField(default=uuid4, max_length=64)
    upload_folder = models.CharField(default="", max_length=1024)
    archive_folder = models.CharField(default="", max_length=1024)
    notification_enabled = models.SmallIntegerField(choices=((0, "No"), (1, "Yes")), default=0)

    def __str__(self):
        return self.user.username


class Notification(_OwnerModel):
    msg = models.CharField(max_length=500)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, delegate=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    try:
        instance.queuedb_profile_related.save()
    except Exception as e:
        print(e)


class Sample(_OwnerModel):
    name = models.CharField(max_length=500)
    file_path = models.TextField()  # real file path with uploads as prefix
    inner_path = models.TextField()  # file path without uploads as prefix
    experiment = models.ForeignKey(Experiment, on_delete=models.PROTECT, related_name="%(app_label)s_%(class)s_related")
    attribute = models.TextField(blank=True, null=True)
    create_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class FileArchive(_OwnerModel):
    protocol = models.ForeignKey('ProtocolList', on_delete=models.CASCADE,
                                 related_name="%(app_label)s_%(class)s_related")
    protocol_ver = models.CharField(max_length=33, null=True)
    inputs = models.TextField()
    files = models.TextField()
    file_md5s = models.TextField()
    job = models.ForeignKey(Job, on_delete=models.CASCADE, null=True, blank=True)
    raw_files = models.TextField(null=True, blank=True)
    audit = models.SmallIntegerField(default=0)
    description = models.TextField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    status = models.SmallIntegerField(default=0)
    archive_file = models.TextField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    shared_with = models.TextField(null=True, blank=True)
    file_id_remote = models.TextField(null=True, blank=True, default="ph")


class Workspace(_OwnerModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return "%s - %s" % (self.name, self.user.username)


@receiver(pre_delete, sender=Sample, dispatch_uid="sample_delete_signal")
def remove_sample_links(sender, instance, using, **kwargs):
    """
    Check the existence of symbolic links to the sample
    and if there's any, remove them

    Parameters
    ----------
    sender :
    instance :
    using :
    kwargs :

    Returns
    -------

    """
    import base64
    import os

    if instance.user.queuedb_profile_related.delegate.queuedb_profile_related.upload_folder != "":
        for file in instance.inner_path.split(";"):
            # users_upload_path = os.path.join(get_config('env', 'workspace'),
            #                                  str(instance.user.profile.delegate.id),
            #                                  "uploads")
            users_upload_path = "t"
            potential_link_path = os.path.join(users_upload_path,
                                               os.path.split(base64.b64decode(file).decode("utf-8"))[1])

            # make sure the file exist and it's a symbolic link
            if os.path.exists(potential_link_path) and os.path.islink(potential_link_path):
                os.remove(potential_link_path)


# import plugin models
# from .extmodels.GoogleDrive import GoogleDriveConnection
# from .extmodels.RunOnQC import RunOnQualityReport
