from django.apps import AppConfig


class QueuedbConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "QueueDB"

    def ready(self):
        from django.db.backends.signals import connection_created

        from QueueDB.sqlite_setup import configure_sqlite_connection

        connection_created.connect(
            lambda sender, connection, **kwargs: configure_sqlite_connection(connection),
            dispatch_uid="queuedb.sqlite_wal",
        )
