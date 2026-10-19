from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("QueueDB", "0053_sync_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="slave",
            name="stage_in",
            field=models.SmallIntegerField(
                blank=True,
                choices=[(0, "Off"), (1, "On")],
                default=None,
                help_text="Blank inherits cluster.stage_in from custom.conf.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="slave",
            name="scripts_dir",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Shared directory on the cluster for uploaded sbatch scripts.",
                max_length=2048,
            ),
        ),
        migrations.AddField(
            model_name="slave",
            name="result_root",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Shared directory the worker fetches results from.",
                max_length=2048,
            ),
        ),
        migrations.AddField(
            model_name="slave",
            name="log_root",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Shared directory for Slurm stdout and stderr.",
                max_length=2048,
            ),
        ),
        migrations.AddField(
            model_name="slave",
            name="workdir",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional shared working directory. Blank uses the scripts directory.",
                max_length=2048,
            ),
        ),
        migrations.AlterField(
            model_name="slave",
            name="cluster_manager_path",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Directory containing sbatch, scontrol, and sacct. Blank uses cluster.bin_prefix.",
                max_length=2048,
                null=True,
            ),
        ),
    ]
