#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Li Yao
# @Date: 12/01/16
from django.contrib import admin
from QueueDB.models import Job, Training, Prediction, Step, ProtocolList, VirtualEnvironment, Experiment, \
    Audition, Sample, Profile, FileArchive, Reference, Workspace #, GoogleDriveConnection

'''
class QueueInline(admin.StackedInline):
    model = ProtocolList
'''


class QueueAdmin(admin.ModelAdmin):
    # inlines = [QueueInline]
    list_display = ('id', 'job_name', 'protocol', 'status', 'result', 'create_time')
    search_fields = ('result', 'job_name',)


class TrainingAdmin(admin.ModelAdmin):
    list_display = ('id', 'step_name', 'input', 'output', 'mem_in_gb', 'vrt_mem_in_gb', 'cpu', 'create_time')


class PredictionAdmin(admin.ModelAdmin):
    list_display = ('id', 'step_name', 'step_hash', 'a', 'b', 'r', 'type')


class ResourceAdmin(admin.ModelAdmin):
    list_display = ('cpu', 'mem', 'disk', 'lock')


class ProtocolAdmin(admin.ModelAdmin):
    list_display = ('software', 'parameter', 'specify_output', 'parent')


class ProtocolListAdmin(admin.ModelAdmin):
    list_display = ('name', 'user_id')


class FileArchiveAdmin(admin.ModelAdmin):
    list_display = ('protocol', 'protocol_ver', 'create_time', 'shared_with')


class ReferenceAdmin(admin.ModelAdmin):
    list_display = ('name', 'user_id')


class AuditionAdmin(admin.ModelAdmin):
    list_display = ('id', 'operation', 'job_name', 'create_time')
    readonly_fields = ['id', 'operation', 'related_job', 'job_name', 'prev_par',
                       'new_par', 'prev_input', 'current_input', 'protocol',
                       'protocol_ver', 'resume_point', 'create_time', 'user']


admin.site.register(Job, QueueAdmin)
admin.site.register(Prediction, PredictionAdmin)
admin.site.register(Training, TrainingAdmin)
admin.site.register(ProtocolList, ProtocolListAdmin)
admin.site.register(Step, ProtocolAdmin)
admin.site.register(VirtualEnvironment)
admin.site.register(Experiment)
admin.site.register(Sample)
admin.site.register(Profile)
admin.site.register(FileArchive, FileArchiveAdmin)
admin.site.register(Reference, ReferenceAdmin)
admin.site.register(Workspace)
# admin.site.register(GoogleDriveConnection)
admin.site.register(Audition, AuditionAdmin)
