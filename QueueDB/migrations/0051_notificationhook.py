from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("QueueDB", "0050_protocollist_template_job_sample_sheet"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationHook",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("provider", models.CharField(max_length=32)),
                ("enabled", models.SmallIntegerField(choices=[(0, "No"), (1, "Yes")], default=1)),
                ("events", models.CharField(default="finished,failed,interrupted", max_length=120)),
                ("config", models.TextField(blank=True, default="")),
                ("create_time", models.DateTimeField(auto_now_add=True)),
                ("update_time", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_hooks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
        migrations.AddIndex(
            model_name="notificationhook",
            index=models.Index(fields=["user", "enabled"], name="notifhook_user_enabled"),
        ),
    ]
