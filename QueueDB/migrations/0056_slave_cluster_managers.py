from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("QueueDB", "0055_slave_cluster_path_columns"),
    ]

    operations = [
        migrations.AlterField(
            model_name="slave",
            name="cluster_manager",
            field=models.SmallIntegerField(
                choices=[
                    (0, "Local"),
                    (1, "Slurm"),
                    (2, "LSF"),
                    (3, "TorquePBS"),
                    (4, "HTCondor"),
                ],
                default=0,
                help_text=(
                    "Local runs the command on this machine. A cluster manager "
                    "runs its commands here when SSH host is blank. Slurm uses "
                    "SSH when a host is set."
                ),
            ),
        ),
    ]
