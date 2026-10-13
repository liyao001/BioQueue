from django.db import migrations


# 0054 adds these columns. A faked migrate records 0054 without altering
# QueueDB_slave, so create any of them that are still missing.
_COLUMNS = ("stage_in", "scripts_dir", "result_root", "log_root", "workdir")


def add_missing_slave_columns(apps, schema_editor):
    Slave = apps.get_model("QueueDB", "Slave")
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        existing = {
            column.name
            for column in connection.introspection.get_table_description(
                cursor, Slave._meta.db_table
            )
        }
    for name in _COLUMNS:
        if name in existing:
            continue
        schema_editor.add_field(Slave, Slave._meta.get_field(name))


class Migration(migrations.Migration):

    dependencies = [
        ("QueueDB", "0055_merge_20261010_1247"),
    ]

    operations = [
        migrations.RunPython(add_missing_slave_columns, migrations.RunPython.noop),
    ]
