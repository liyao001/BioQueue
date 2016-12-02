from django.contrib import admin

from .models import Queue, ProtocolList

'''
class QueueInline(admin.StackedInline):
    model = ProtocolList
'''


class QueueAdmin(admin.ModelAdmin):
    # inlines = [QueueInline]
    list_display = ('id', 'protocol', 'create_time')

admin.site.register(Queue, QueueAdmin)
