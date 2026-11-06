from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("apk", "0005_apksubmission_source_created_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="kursant",
            name="kind",
            field=models.CharField(
                choices=[
                    ("apk_kursant", "APK kursant"),
                    ("osint_kursant", "OSINT kursant"),
                ],
                db_index=True,
                default="apk_kursant",
                max_length=24,
                verbose_name="Turi",
            ),
        ),
    ]
