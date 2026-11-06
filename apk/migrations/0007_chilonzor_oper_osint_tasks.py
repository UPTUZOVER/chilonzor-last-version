from django.db import migrations, models
import django.db.models.deletion


def create_chilonzor_oper_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    db_alias = schema_editor.connection.alias
    Group.objects.using(db_alias).get_or_create(name="chilonzor_oper")


def remove_chilonzor_oper_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    db_alias = schema_editor.connection.alias
    group = Group.objects.using(db_alias).filter(name="chilonzor_oper").first()
    if group and not group.user_set.using(db_alias).exists():
        group.delete(using=db_alias)


class Migration(migrations.Migration):

    dependencies = [
        ("apk", "0006_kursant_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="OsintTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200, verbose_name="Sarlavha")),
                ("description", models.TextField(verbose_name="Tavsif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("submitted_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="osint_tasks_sent", to="app.users", verbose_name="Yuborgan")),
            ],
            options={
                "verbose_name": "Akademiya topshirig'i",
                "verbose_name_plural": "Akademiya topshiriqlari",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="OsintTaskValue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Tartib")),
                ("telegram_id", models.CharField(max_length=100, verbose_name="Telegram ID")),
                ("value", models.CharField(max_length=255, verbose_name="Qiymat")),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="apk.osinttask", verbose_name="Topshiriq")),
            ],
            options={
                "verbose_name": "Telegram ID va qiymat",
                "verbose_name_plural": "Telegram ID va qiymatlar",
                "ordering": ["order", "id"],
            },
        ),
        migrations.RunPython(create_chilonzor_oper_group, remove_chilonzor_oper_group),
    ]
