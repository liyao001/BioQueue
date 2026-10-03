from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("QueueDB", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="protocollist",
            name="template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="job",
            name="sample_sheet",
            field=models.TextField(blank=True, default=""),
        ),
    ]
