from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("territories", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="territory",
            old_name="gadm_gid",
            new_name="external_id",
        ),
        migrations.AlterField(
            model_name="territory",
            name="external_id",
            field=models.CharField(
                max_length=40, unique=True, verbose_name="ID источника"
            ),
        ),
    ]
