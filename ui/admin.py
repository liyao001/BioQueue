from django.contrib import admin

from .models import Queue, Training, Prediction, Resource

'''
class QueueInline(admin.StackedInline):
    model = ProtocolList
'''


class QueueAdmin(admin.ModelAdmin):
    # inlines = [QueueInline]
    list_display = ('id', 'protocol', 'status', 'resume', 'create_time')


class TrainingAdmin(admin.ModelAdmin):
    list_display = ('id', 'step_name', 'input', 'output', 'mem', 'cpu', 'create_time')


class PredictionAdmin(admin.ModelAdmin):
    list_display = ('id', 'step_name', 'step_hash', 'a', 'b', 'r', 'type')


class ResourceAdmin(admin.ModelAdmin):
    list_display = ('cpu', 'mem', 'disk', 'lock')

admin.site.register(Queue, QueueAdmin)
admin.site.register(Prediction, PredictionAdmin)
admin.site.register(Training, TrainingAdmin)
admin.site.register(Resource, ResourceAdmin)
