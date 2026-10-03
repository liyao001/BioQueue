from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("QueueDB", "0050_protocollist_template_job_sample_sheet"),
    ]

    operations = [
        migrations.AddField(
            model_name="virtualenvironment",
            name="recipe",
            field=models.TextField(blank=True, default=""),
        ),
    ]
