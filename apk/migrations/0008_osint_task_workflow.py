from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("apk", "0007_chilonzor_oper_osint_tasks"),
    ]

    operations = [
        migrations.AddField(
            model_name="kursant",
            name="osint_points",
            field=models.PositiveIntegerField(default=0, verbose_name="OSINT ballari"),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "Yangi"),
                    ("student_working", "OSINT kursant ish boshladi"),
                    ("sent", "Operator ko'rishini kutmoqda"),
                    ("operator_working", "Operator ishni ko'rib chiqmoqda"),
                    ("returned", "Kursantga qaytarildi"),
                    ("accepted", "Tasdiqlandi"),
                ],
                db_index=True,
                default="new",
                max_length=24,
                verbose_name="Holat",
            ),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="student_claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="student_submitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="operator_claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="return_note",
            field=models.TextField(blank=True, default="", verbose_name="Qaytarish sababi"),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="points_awarded",
            field=models.BooleanField(default=False, verbose_name="Ball berildi"),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="student",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="osint_tasks_claimed",
                to="app.users",
                verbose_name="OSINT kursant",
            ),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="operator",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="osint_tasks_operating",
                to="app.users",
                verbose_name="Ishni olgan operator",
            ),
        ),
        migrations.AddField(
            model_name="osinttask",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="osint_tasks_reviewed",
                to="app.users",
                verbose_name="Ko'rib chiqqan operator",
            ),
        ),
        migrations.CreateModel(
            name="OsintTaskResult",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Tartib")),
                ("telegram_id", models.CharField(max_length=100, verbose_name="Telegram ID")),
                ("value", models.CharField(max_length=255, verbose_name="Qiymat")),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="results",
                        to="apk.osinttask",
                        verbose_name="Topshiriq",
                    ),
                ),
            ],
            options={
                "verbose_name": "OSINT natijasi",
                "verbose_name_plural": "OSINT natijalari",
                "ordering": ["order", "id"],
            },
        ),
    ]
