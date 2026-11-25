import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("QueueDB", "0056_slave_cluster_managers"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApiIdempotency",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=200)),
                ("request_hash", models.CharField(max_length=64)),
                ("status_code", models.PositiveSmallIntegerField(default=0)),
                ("response_body", models.TextField(blank=True, default="")),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="api_idempotency",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="apiidempotency",
            constraint=models.UniqueConstraint(fields=("user", "key"), name="api_idempotency_user_key"),
        ),
    ]
