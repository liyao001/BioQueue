from django.apps import AppConfig


class Ui3Config(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "ui"
    verbose_name = "BioQueue"

    def ready(self):
        from ui import plugins

        plugins.autodiscover()
