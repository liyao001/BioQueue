from django.apps import AppConfig


class Ui3Config(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "ui3"
    verbose_name = "BioQueue UI version 3"

    def ready(self):
        from ui3 import plugins

        plugins.autodiscover()
