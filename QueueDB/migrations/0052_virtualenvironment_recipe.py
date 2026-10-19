from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("QueueDB", "0051_notificationhook"),
    ]

    operations = [
        migrations.AddField(
            model_name="virtualenvironment",
            name="recipe",
            field=models.TextField(blank=True, default=""),
        ),
    ]
