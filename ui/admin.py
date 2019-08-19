from django.contrib import admin

from .models import Queue, Training, Prediction, Resource, Protocol, ProtocolList, VirtualEnvironment

'''
class QueueInline(admin.StackedInline):
    model = ProtocolList
'''


class QueueAdmin(admin.ModelAdmin):
    # inlines = [QueueInline]
    list_display = ('id', 'protocol', 'status', 'resume', 'create_time')


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


admin.site.register(Queue, QueueAdmin)
admin.site.register(Prediction, PredictionAdmin)
admin.site.register(Training, TrainingAdmin)
admin.site.register(Resource, ResourceAdmin)
admin.site.register(ProtocolList, ProtocolListAdmin)
admin.site.register(Protocol, ProtocolAdmin)
admin.site.register(VirtualEnvironment)
