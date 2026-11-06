from django.db import migrations


GROUP_NAME = "Chilonzor admin 03"


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.using(schema_editor.connection.alias).get_or_create(name=GROUP_NAME)


def remove_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    db_alias = schema_editor.connection.alias
    group = Group.objects.using(db_alias).filter(name=GROUP_NAME).first()
    if group and not group.user_set.using(db_alias).exists():
        group.delete(using=db_alias)


class Migration(migrations.Migration):
    dependencies = [("apk", "0010_chilonzor_admin_groups")]

    operations = [migrations.RunPython(create_group, remove_group)]
