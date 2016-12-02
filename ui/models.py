from __future__ import unicode_literals
from django.http import HttpResponse
from django.db import models


class Prediction(models.Model):
    """Prediction Table
    Save linear model for memory, output size
    Or average, sd for CPU
    """
    step_hash = models.CharField(max_length=50, db_index=True)
    a = models.CharField(max_length=50, blank=True, null=True)
    b = models.CharField(max_length=50, blank=True, null=True)
    r = models.CharField(max_length=50, blank=True, null=True)
    type = models.SmallIntegerField()

    def __str__(self):
        return self.step_hash


class Protocol(models.Model):
    """Protocol Table
    Save steps for protocol
    """
    software = models.CharField(max_length=50)
    parameter = models.TextField()
    specify_output = models.CharField(max_length=50, blank=True, null=True)
    parent = models.CharField(max_length=50, db_index=True)
    user_id = models.CharField(max_length=50)
    hash = models.CharField(max_length=50)

    def __str__(self):
        return self.hash

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
    name = models.CharField(max_length=50)
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
        self.save()

    def resume_job(self):
        self.status = 0
        self.save()

    def get_result(self):
        return self.result


class References(models.Model):
    """Reference Table
    Save custom references
    """
    name = models.CharField(max_length=50)
    path = models.CharField(max_length=50)
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
    cpu = models.CharField(max_length=50, blank=True, null=True)
    create_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.step
