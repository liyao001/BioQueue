from __future__ import unicode_literals
from django.http import HttpResponse
from django.db import models


PREDICTION_CHOICES = (
    (1, 'Disk'),
    (2, 'Memory'),
    (3, 'CPU'),
    (4, 'Virtual Memory'),
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


class Prediction(models.Model):
    """Prediction Table
    Save linear model for memory, output size
    Or average, sd for CPU
    """
    step_hash = models.CharField(max_length=50, db_index=True)
    a = models.CharField(max_length=50, blank=True, null=True)
    b = models.CharField(max_length=50, blank=True, null=True)
    r = models.CharField(max_length=50, blank=True, null=True)
    type = models.SmallIntegerField(choices=PREDICTION_CHOICES)

    def __str__(self):
        return self.step_hash

    def step_name(self):
        """
        step = Protocol.objects.filter(hash=self.step_hash)
        return step[0].software+' '+step[0].parameter
        """
        steps = Protocol.objects.filter(hash=self.step_hash)
        step_key = None
        if steps:
            step_key = steps[0]
        if step_key:
            return step_key.software + ' ' + step_key.parameter
        else:
            return ''

    step_name.admin_order_field = 'step_hash'


class Protocol(models.Model):
    """Protocol Table
    Save steps for protocol
    """
    software = models.CharField(max_length=50)
    parameter = models.TextField()
    specify_output = models.CharField(max_length=50, blank=True, null=True)
    # parent = models.CharField(max_length=50, db_index=True)
    parent = models.ForeignKey('ProtocolList')
    user_id = models.CharField(max_length=50)
    hash = models.CharField(max_length=50)
    step_order = models.SmallIntegerField(default=1)
    force_local = models.SmallIntegerField(default=0, choices=YES_OR_NO)

    def __str__(self):
        return self.software+' '+self.parameter

    def check_owner(self, user):
        if int(self.user_id) == user:
            return 1
        else:
            return 0

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
        m = hashlib.md5()
        m.update(self.software + ' ' + new_parameter.strip())
        self.hash = m.hexdigest()
        self.parameter = new_parameter
        return 1


class ProtocolList(models.Model):
    """Protocol List Table
    Save protocol names
    """
    name = models.CharField(max_length=500)
    user_id = models.CharField(max_length=50)

    def __str__(self):
        return self.name

    def check_owner(self, user):
        if int(self.user_id) == user:
            return 1
        else:
            return 0


class Queue(models.Model):
    """Queue Table
    Save tasks
    """
    protocol = models.ForeignKey('ProtocolList')
    job_name = models.CharField(max_length=100, blank=True, null=True)
    input_file = models.TextField()
    parameter = models.TextField()
    run_dir = models.TextField(blank=True, null=True)
    result = models.TextField(blank=True, null=True)
    status = models.SmallIntegerField(default=0)
    update_time = models.DateTimeField(auto_now=True)
    create_time = models.DateTimeField(auto_now_add=True)
    user_id = models.CharField(max_length=50)
    resume = models.SmallIntegerField(default=-1)
    ter = models.SmallIntegerField(default=0)
    wait_for = models.SmallIntegerField(default=0, choices=CHECKPOINT_CHOICES)

    def __str__(self):
        return str(self.id)

    def check_owner(self, user):
        if int(self.user_id) == user:
            return 1
        else:
            return 0

    def terminate_job(self):
        self.ter = 1
        self.save()

    def rerun_job(self):
        self.status = 0
        self.resume = -1
        self.ter = 0
        self.save()

    def resume_job(self, rollback):
        self.resume = rollback
        self.status = 0
        self.save()

    def set_result(self, value):
        self.result = value
        self.save()

    def set_status(self, status):
        self.status = status
        self.save()

    def set_wait(self, for_what):
        self.status = -2
        self.wait_for = for_what
        self.save()

    def get_result(self):
        return self.result

    def update_status(self, status):
        self.status = status
        self.save()


class References(models.Model):
    """Reference Table
    Save custom references
    """
    name = models.CharField(max_length=255)
    path = models.CharField(max_length=500)
    description = models.TextField()
    user_id = models.CharField(max_length=50)

    def __str__(self):
        return self.name

    def check_owner(self, user):
        if int(self.user_id) == user:
            return 1
        else:
            return 0


class Resource(models.Model):
    """Resource Table
    Save system resource
    """
    cpu = models.CharField(max_length=50)
    mem = models.CharField(max_length=50)
    disk = models.CharField(max_length=50)
    own = models.CharField(max_length=50, default='sys')
    lock = models.SmallIntegerField(default=0)

    def __str__(self):
        return str(self.cpu)


class Training(models.Model):
    """Training Table
    Save training items
    """
    step = models.CharField(max_length=50, db_index=True)
    input = models.CharField(max_length=50, blank=True, null=True)
    output = models.CharField(max_length=50, blank=True, null=True)
    mem = models.CharField(max_length=50, blank=True, null=True)
    vrt_mem = models.CharField(max_length=50, blank=True, null=True)
    cpu = models.CharField(max_length=50, blank=True, null=True)
    create_time = models.DateTimeField(auto_now_add=True)
    lock = models.SmallIntegerField(default=1)

    def __str__(self):
        return self.step

    def step_name(self):
        steps = Protocol.objects.filter(hash=self.step)
        step_key = None
        if steps:
            step_key = steps[0]
        if step_key:
            return step_key.software+' '+step_key.parameter
        else:
            return ''

    def update_cpu_mem(self, cpu, mem, vrt_mem):
        self.mem = mem
        self.cpu = cpu
        self.vrt_mem = vrt_mem
        self.save()

    def mem_in_gb(self):
        if self.mem:
            try:
                return str(round(float(self.mem) / 1024 / 1024 / 1024, 2))+'GB'
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
