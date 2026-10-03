# @Author: Li Yao
# @Date: 12/01/16


from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

_YES = 1
_NO = 0

_PD_DISK = 1
_PD_MEM = 2
_PD_CPU = 3
_PD_VRTMEM = 4
PREDICTION_CHOICES = (
    (_PD_DISK, "Disk"),
    (_PD_MEM, "Memory"),
    (_PD_CPU, "CPU"),
    (_PD_VRTMEM, "Virtual Memory"),
)

CHECKPOINT_CHOICES = (
    (0, "Ok"),
    (1, "Disk"),
    (2, "Memory"),
    (3, "CPU"),
    (4, "Former"),
    (5, "Peer"),
    (6, "Virtual Memory"),
)

YES_OR_NO = ((0, "No"), (1, "Yes"))

OPERATIONS_FOR_AUDITION = (
    (0, "Created a job"),
    (1, "Rerun a job"),
    (2, "Resumed a job"),
    (3, "Finished a job"),
    (4, "Deleted a job"),
)


class JobStatus(models.IntegerChoices):
    WRONG = -3, _("Failed")
    RESOURCELOCK = -2, _("Waiting for resources")
    FINISHED = -1, _("Finished")
    WAITING = 0, _("Waiting")
    RUNNING = 1, _("Running")
    INTERRUPTED = 2, _("Interrupted")


_JS_WRONG = JobStatus.WRONG.value
_JS_RESOURCELOCK = JobStatus.RESOURCELOCK.value
_JS_FINISHED = JobStatus.FINISHED.value
_JS_WAITING = JobStatus.WAITING.value
_JS_RUNNING = JobStatus.RUNNING.value
_JS_INTERRUPTED = JobStatus.INTERRUPTED.value
JOB_STATUS = JobStatus.choices


class _OwnerModel(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_related",
    )

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
        elif int(self.user.id) == user.id or user.is_staff:  # owner
            return True
        else:
            return False


class Slave(models.Model):
    name = models.CharField(max_length=100, unique=True)
    comment = models.TextField()
    is_master = models.SmallIntegerField(default=0, choices=((0, "No"), (1, "Yes")))
    ssh_connection = models.CharField(
        max_length=1024,
        null=True,
        blank=True,
        help_text="Provide ssh connection info for fabric if this is a remote node",
    )
    ssh_user = models.CharField(
        max_length=1024, null=True, blank=True, help_text="SSH user"
    )
    ssh_key = models.CharField(
        max_length=2048, null=True, blank=True, help_text="SSH private key file"
    )
    cluster_manager = models.SmallIntegerField(
        choices=(
            (0, "Local"),
            (1, "Slurm"),
        ),
        default=0,
        help_text="Specify the cluster manager if this node is from a cluster",
    )
    cluster_manager_path = models.CharField(
        max_length=2048,
        null=True,
        blank=True,
        default="",
    )

    def __str__(self):
        return self.name


class Audition(_OwnerModel):
    operation = models.CharField(max_length=50)
    related_job = models.ForeignKey("Job", on_delete=models.SET_NULL, null=True)
    job_name = models.CharField(max_length=100)
    job_ver = models.IntegerField(null=True, default=0)
    prev_par = models.TextField()
    new_par = models.TextField()
    prev_input = models.TextField()
    current_input = models.TextField()
    protocol = models.CharField(max_length=100)
    protocol_ver = models.CharField(max_length=100)
    resume_point = models.SmallIntegerField(default=-1)
    create_time = models.DateTimeField(auto_now_add=True)
    comments = models.TextField(null=True)


class VirtualEnvironment(_OwnerModel):
    """Virtual Environment Table
    Save VEs which can be activated by source command
    """

    name = models.CharField(max_length=50)
    ve_type = models.CharField(
        choices=(("conda", "conda"), ("venv", "venv")), max_length=10, default="conda"
    )
    value = models.TextField()
    activation_command = models.TextField(null=True, blank=True)
    recipe = models.TextField(blank=True, default="")
    recipe = models.TextField(blank=True, default="")

    class Meta:
        try:
            constraints = [
                models.UniqueConstraint(fields=["name", "user"], name="unique_name")
            ]
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
            return step_key.software + " " + step_key.parameter
        else:
            return ""

    step_name.admin_order_field = "step_hash"


class Step(_OwnerModel):
    """Protocol Table
    Save steps for protocol
    """

    software = models.CharField(max_length=128)
    parameter = models.TextField()
    specify_output = models.CharField(max_length=50, blank=True, null=True)
    parent = models.ForeignKey("ProtocolList", on_delete=models.CASCADE)
    hash = models.CharField(max_length=50)
    step_order = models.SmallIntegerField(default=1)
    env = models.ForeignKey(
        "VirtualEnvironment", blank=True, null=True, on_delete=models.PROTECT
    )
    force_local = models.SmallIntegerField(default=0, choices=YES_OR_NO)
    version_check = models.TextField(default="", blank=True)
    cpu_prior = models.IntegerField(default=-1, blank=True)
    mem_prior = models.IntegerField(default=-1, blank=True)
    disk_prior = models.IntegerField(default=-1, blank=True)
    gpu_step = models.SmallIntegerField(default=0, choices=((0, "CPU"), (1, "GPU")))
    step_comment = models.TextField(default="", blank=True, null=True)

    def __str__(self):
        return self.software + " " + self.parameter

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

        m = hashlib.md5(str(self.software + " " + new_parameter.strip()).encode())
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
    # Compact protocol (samples, blocks, pipeline). Empty means a plain step list.
    template = models.TextField(blank=True, default="")

    def __str__(self):
        return f"{self.name} - {self.user}"


class Job(_OwnerModel):
    """Queue Table
    Save tasks
    """

    class JobAudit(models.IntegerChoices):
        OK = 0, _("Ok")
        IN_CHANGED = 1, _("Input/Parameters changed")
        PRT_CHANGED = 2, _("Protocol/Reference changed")
        OUT_CHANGED = 3, _("Output modified outside of the platform")

    parent_job = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, editable=False
    )
    protocol = models.ForeignKey("ProtocolList", on_delete=models.CASCADE)
    protocol_ver = models.CharField(max_length=100, blank=True, null=True)
    job_name = models.CharField(max_length=100, blank=True, null=True, default="")
    input_file = models.TextField(blank=True)
    parameter = models.TextField(blank=True)
    # Optional JSON list of per-replicate records for a protocol template.
    sample_sheet = models.TextField(blank=True, default="")
    run_dir = models.TextField(null=True)
    result = models.TextField(blank=True, null=True)
    status = models.SmallIntegerField(default=JobStatus.WAITING, choices=JOB_STATUS)
    update_time = models.DateTimeField(auto_now=True)
    create_time = models.DateTimeField(auto_now_add=True)
    resume = models.SmallIntegerField(default=0)
    ter = models.SmallIntegerField(default=_NO, choices=YES_OR_NO)
    audit = models.SmallIntegerField(default=_NO, choices=JobAudit.choices)
    wait_for = models.SmallIntegerField(default=0, choices=CHECKPOINT_CHOICES)
    workspace = models.ForeignKey(
        "Workspace", blank=True, null=True, on_delete=models.PROTECT
    )
    locked = models.SmallIntegerField(
        choices=((1, "Locked"), (0, "Not locked")), default=0
    )
    comments = models.TextField(blank=True, null=True)
    is_gpu_job = models.SmallIntegerField(
        default=0, choices=((0, "CPU job"), (1, "GPU job"))
    )
    version = models.IntegerField(default=-1, blank=True, null=True)
    slave = models.ForeignKey(
        "Slave", null=True, on_delete=models.DO_NOTHING, blank=True
    )
    array_setting = models.CharField(max_length=100, blank=True, null=True)
    visibility = models.SmallIntegerField(
        default=1, choices=((0, "Hide"), (1, "Visible"), (2, "Visible in workspace"))
    )
    is_executable = models.SmallIntegerField(
        default=1, choices=((0, "no"), (1, "yes")), editable=False
    )
    insitu = models.SmallIntegerField(
        default=0,
        choices=((0, "ex situ"), (1, "in situ")),
        help_text="Rerun the job in the same folder?",
    )

    def __str__(self):
        return str(self.id) + "-" + self.job_name

    def terminate_job(self):
        self.ter = 1
        self.save()
        Audition(
            operation="Terminated",
            related_job=self,
            job_ver=self.version,
            job_name=self.job_name,
            prev_par=self.parameter,
            new_par=self.parameter,
            prev_input=self.input_file,
            current_input=self.input_file,
            protocol=self.protocol.name,
            protocol_ver=self.protocol_ver,
            resume_point=self.resume,
            user=self.user,
        ).save()
        if self.is_executable == 0:
            for child_job in Job.objects.filter(parent_job=self):
                child_job.terminate_job()

    def rerun_job(self, insitu=0):
        if not self.locked:
            self.status = 0
            self.resume = 0
            self.ter = 0
            self.protocol_ver = self.protocol.ver
            self.audit = 0
            self.insitu = insitu
            self.save()
            Audition(
                operation="Reran",
                related_job=self,
                job_name=self.job_name,
                job_ver=self.version,
                prev_par=self.parameter,
                new_par=self.parameter,
                prev_input=self.input_file,
                current_input=self.input_file,
                protocol=self.protocol.name,
                protocol_ver=self.protocol_ver,
                resume_point=self.resume,
                user=self.user,
            ).save()
            if self.is_executable == 0:
                for child_job in Job.objects.filter(parent_job=self):
                    # no need to delete files, since they are moved to the parent folder
                    # and get taken care when the parent job reruns.
                    child_job.rerun_job()

    def resume_job(self, rollback):
        if not self.locked:
            self.resume = rollback
            self.status = 0
            self.protocol_ver = self.protocol.ver
            self.audit = 0
            self.save()
            Audition(
                operation="Resumed",
                related_job=self,
                job_name=self.job_name,
                job_ver=self.version,
                prev_par=self.parameter,
                new_par=self.parameter,
                prev_input=self.input_file,
                current_input=self.input_file,
                protocol=self.protocol.name,
                protocol_ver=self.protocol_ver,
                resume_point=self.resume,
                user=self.user,
            ).save()

    def set_done(self):
        if not self.locked:
            self.status = JobStatus.FINISHED
            self.save()
            Audition(
                operation="Done",
                related_job=self,
                job_name=self.job_name,
                job_ver=self.version,
                prev_par=self.parameter,
                new_par=self.parameter,
                prev_input=self.input_file,
                current_input=self.input_file,
                protocol=self.protocol.name,
                protocol_ver=self.protocol_ver,
                resume_point=self.resume,
                user=self.user,
            ).save()
            if self.user.queuedb_profile_related.notification_enabled:
                Notification(
                    msg=self.job_name + " (" + str(self.id) + ") " + "is done.",
                    user=self.user,
                ).save()

    def set_result(self, value):
        if not self.locked:
            self.result = value
            self.save()

    def set_status(self, status):
        if not self.locked:
            self.status = status
            self.save()

    def set_wait(self, for_what):
        if not self.locked:
            self.status = JobStatus.WAITING
            self.wait_for = for_what
            self.save()

    def get_result(self):
        return self.result

    def update_status(self, status):
        if not self.locked:
            self.status = status
            self.save()

    def update_inputs(self, new_inputs):
        if not self.locked:
            Audition(
                operation="Changed inputs",
                related_job=self,
                job_name=self.job_name,
                job_ver=self.version,
                prev_par=self.parameter,
                new_par=self.parameter,
                prev_input=self.input_file,
                current_input=new_inputs,
                protocol=self.protocol.name,
                protocol_ver=self.protocol_ver,
                resume_point=self.resume,
                user=self.user,
            ).save()
            self.input_file = new_inputs
            self.audit = 1
            self.save()

    def update_parameter(self, new_par):
        if not self.locked:
            Audition(
                operation="Changed parameters",
                related_job=self,
                job_name=self.job_name,
                job_ver=self.version,
                prev_par=self.parameter,
                new_par=new_par,
                prev_input=self.input_file,
                current_input=self.input_file,
                protocol=self.protocol.name,
                protocol_ver=self.protocol_ver,
                resume_point=self.resume,
                user=self.user,
            ).save()
            self.parameter = new_par
            self.audit = 1
            self.save()

    def update_comments(self, new_comments):
        if not self.locked:
            Audition(
                operation="Changed comments",
                related_job=self,
                job_name=self.job_name,
                job_ver=self.version,
                prev_par=self.parameter,
                new_par=self.parameter,
                prev_input=self.input_file,
                current_input=self.input_file,
                protocol=self.protocol.name,
                protocol_ver=self.protocol_ver,
                resume_point=self.resume,
                user=self.user,
                comments=new_comments or "",
            ).save()
            self.comments = new_comments
            self.audit = 0  # update comments does not trigger audit
            self.save()

    def save(self, *args, **kwargs):
        if "update_fields" in kwargs:
            kwargs["update_fields"] = list(
                set(
                    list(kwargs["update_fields"])
                    + [
                        "update_time",
                    ]
                )
            )
        return super().save(*args, **kwargs)

    class Meta:
        ordering = [
            "id",
        ]


# class PostJobHook(_OwnerModel):
#     """Hooks for different protocols

#     """
#     protocol = models.ForeignKey(ProtocolList, on_delete=models.CASCADE)
#     display_text = models.CharField(max_length=100)
#     display_style = models.CharField(default="btn btn-primary px-2 py-0")
#     action = models.CharField(max_length=100)


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
            return step_key.software + " " + step_key.parameter
        else:
            return "Step missing"

    def update_cpu_mem(self, cpu, mem, vrt_mem):
        self.mem = mem
        self.cpu = cpu
        self.vrt_mem = vrt_mem
        self.save()

    def mem_in_gb(self):
        if self.mem:
            try:
                return str(round(float(self.mem) / 1024 / 1024 / 1024, 2)) + "GB"
            except:
                return ""
        else:
            return "-"

    def vrt_mem_in_gb(self):
        if self.vrt_mem:
            try:
                return str(round(float(self.vrt_mem) / 1024 / 1024 / 1024, 2)) + "GB"
            except:
                return ""
        else:
            return "-"

    step_name.admin_order_field = "step"


class Experiment(models.Model):
    name = models.CharField(max_length=300)
    required_fields = models.TextField()
    file_support = models.CharField(null=True, blank=True, max_length=500)

    def __str__(self):
        return self.name


class Profile(models.Model):
    from uuid import uuid4

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="%(app_label)s_%(class)s_related"
    )
    delegate = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="%(app_label)s_delegate_related"
    )
    api_key = models.CharField(default=uuid4, max_length=64, unique=True)
    api_secret = models.CharField(default=uuid4, max_length=64)
    upload_folder = models.CharField(default="", blank=True, max_length=1024)
    archive_folder = models.CharField(default="", blank=True, max_length=1024)
    notification_enabled = models.SmallIntegerField(
        choices=((0, "No"), (1, "Yes")), default=0
    )

    def __str__(self):
        return self.user.username

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
        elif int(self.user.id) == user.id or user.is_staff:  # owner
            return True
        else:
            return False


class CrossAccess(_OwnerModel):
    grantee = models.ForeignKey(User, on_delete=models.PROTECT)
    allow_read = models.SmallIntegerField(
        choices=((0, "Deny"), (1, "Allow")), default=1
    )
    allow_write = models.SmallIntegerField(
        choices=((0, "Deny"), (1, "Allow")), default=0
    )

    def __str__(self):
        return "%s -> %s" % (self.user.username, self.grantee.username)


class ProtocolShortcut(_OwnerModel):
    """configurable ui shortcut links for protocols"""

    protocol = models.ForeignKey(
        "ProtocolList",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_related",
        null=True,
        blank=True,
    )
    label = models.CharField(max_length=200)
    href_template = models.TextField(
        help_text="url template, may include {id} placeholder for job id"
    )
    params_template = models.TextField(
        blank=True,
        null=True,
        help_text="optional extra path or query, may include {id}",
    )
    order = models.PositiveIntegerField(default=0)
    active = models.SmallIntegerField(
        default=1, choices=((0, "inactive"), (1, "active"))
    )

    class Meta(_OwnerModel.Meta):
        indexes = [
            models.Index(fields=["protocol", "order"], name="shortcut_protocol_order"),
        ]
        ordering = ["protocol", "order", "id"]

    def __str__(self):
        return f"{self.protocol_id}:{self.label}"


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


@receiver(post_save, sender=Job)
def job_audition(sender, instance, created, **kwargs):
    if created:
        Audition(
            operation="Created a new job",
            related_job=instance,
            job_name=instance.job_name,
            prev_par=instance.parameter,
            new_par=instance.parameter,
            prev_input=instance.input_file,
            current_input=instance.input_file,
            protocol=instance.protocol.name,
            protocol_ver=instance.protocol_ver,
            resume_point=instance.resume,
            user=instance.user,
        ).save()
    else:
        pass


class Sample(_OwnerModel):
    name = models.CharField(max_length=500)
    file_path = models.TextField()  # real file path with uploads as prefix
    inner_path = models.TextField()  # file path without uploads as prefix
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_related",
    )
    attribute = models.TextField(blank=True, null=True)
    create_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class FileArchive(_OwnerModel):
    protocol = models.ForeignKey(
        "ProtocolList",
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_related",
    )
    protocol_ver = models.CharField(max_length=33, null=True)
    inputs = models.TextField()
    files = models.TextField()
    file_md5s = models.TextField()
    job = models.ForeignKey(Job, on_delete=models.PROTECT, null=True, blank=True)
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
        return "%s - %s" % (self.name, self.user)


# Backward-compatible proxies with new names
class Protocol(ProtocolList):
    class Meta(ProtocolList.Meta):
        proxy = True
        verbose_name = "Protocol"
        verbose_name_plural = "Protocols"


class Environment(VirtualEnvironment):
    class Meta(VirtualEnvironment.Meta):
        proxy = True
        verbose_name = "Environment"
        verbose_name_plural = "Environments"


def _recompute_protocol_ver(proto):
    try:
        import hashlib
        import json

        template = (getattr(proto, "template", None) or "").strip()
        if template:
            payload = template
        else:
            steps = (
                Step.objects.filter(parent=proto)
                .values("step_order", "software", "parameter")
                .order_by("step_order", "id")
            )
            canon = [
                {
                    "order": int(s["step_order"]),
                    "software": s["software"],
                    "parameter": (s["parameter"] or ""),
                }
                for s in steps
            ]
            payload = json.dumps(canon, separators=(",", ":"), ensure_ascii=False)
        sig = hashlib.md5(payload.encode("utf-8")).hexdigest()
        if proto.ver != sig:
            proto.ver = sig
            proto.save(update_fields=["ver"])
    except Exception:
        # never block step save on version update
        pass


@receiver(post_save, sender=Step)
def step_changed(sender, instance, created, **kwargs):
    try:
        _recompute_protocol_ver(instance.parent)
    except Exception:
        pass


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

    if (
        instance.user.queuedb_profile_related.delegate.queuedb_profile_related.upload_folder
        != ""
    ):
        for file in instance.inner_path.split(";"):
            # users_upload_path = os.path.join(get_config('env', 'workspace'),
            #                                  str(instance.user.profile.delegate.id),
            #                                  "uploads")
            users_upload_path = "t"
            potential_link_path = os.path.join(
                users_upload_path,
                os.path.split(base64.b64decode(file).decode("utf-8"))[1],
            )

            # make sure the file exist and it's a symbolic link
            if os.path.exists(potential_link_path) and os.path.islink(
                potential_link_path
            ):
                os.remove(potential_link_path)


# import plugin models
