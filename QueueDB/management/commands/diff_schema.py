"""Compare QueueDB models with the live database. Read-only."""

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Report QueueDB tables and columns that differ from the models. Does not change the database."

    def handle(self, *args, **options):
        self._migrations()
        self._tables()

    def _migrations(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        disk = {name for app, name in loader.disk_migrations if app == "QueueDB"}
        applied_rows = {
            name
            for app, name in MigrationRecorder(connection).applied_migrations()
            if app == "QueueDB"
        }
        # Replacements can mark a migration applied only in memory.
        applied_graph = {name for app, name in loader.applied_migrations if app == "QueueDB"}
        conflicts = loader.detect_conflicts().get("QueueDB", [])
        self.stdout.write("migrations")
        if conflicts:
            self.stdout.write("  conflict: " + ", ".join(conflicts))
        else:
            leaves = [name for app, name in loader.graph.leaf_nodes() if app == "QueueDB"]
            self.stdout.write("  leaf: " + ", ".join(leaves))
        for label, names in (
            ("on disk, not recorded", sorted(disk - applied_rows)),
            ("recorded, not on disk", sorted(applied_rows - disk)),
            ("treated as applied by graph, not recorded", sorted(applied_graph - applied_rows)),
        ):
            self.stdout.write(f"  {label}: {len(names)}")
            for name in names:
                self.stdout.write(f"    {name}")

    def _tables(self):
        known = set(connection.introspection.table_names())
        models = [
            model
            for model in apps.get_app_config("QueueDB").get_models()
            if not model._meta.proxy and not model._meta.abstract
        ]
        model_tables = set()
        self.stdout.write("schema")
        with connection.cursor() as cursor:
            for model in sorted(models, key=lambda item: item._meta.db_table):
                table = model._meta.db_table
                model_tables.add(table)
                if table not in known:
                    self.stdout.write(f"  missing table {table} ({model.__name__})")
                    continue
                live = {
                    column.name: column
                    for column in connection.introspection.get_table_description(cursor, table)
                }
                expected = [field for field in model._meta.local_fields if field.column]
                expected_names = {field.column for field in expected}
                missing = sorted(expected_names - set(live))
                extra = sorted(set(live) - expected_names)
                if not missing and not extra:
                    self.stdout.write(f"  {table}: columns match")
                for column in missing:
                    self.stdout.write(f"  {table}: missing column {column}")
                for column in extra:
                    self.stdout.write(f"  {table}: extra column {column}")
                for field in expected:
                    column = live.get(field.column)
                    if column is None or column.null_ok is None:
                        continue
                    if bool(column.null_ok) != bool(field.null):
                        self.stdout.write(
                            f"  {table}.{field.column}: null in database is {bool(column.null_ok)}, model null is {bool(field.null)}"
                        )
        extras = sorted(
            table for table in known if table.lower().startswith("queuedb_") and table not in model_tables
        )
        for table in extras:
            self.stdout.write(f"  extra table {table}")
