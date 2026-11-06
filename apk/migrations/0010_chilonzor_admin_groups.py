from django.db import migrations


GROUP_NAMES = ("Chilonzor admin 01", "Chilonzor admin 02")


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    db_alias = schema_editor.connection.alias
    for name in GROUP_NAMES:
        Group.objects.using(db_alias).get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    db_alias = schema_editor.connection.alias
    for name in GROUP_NAMES:
        group = Group.objects.using(db_alias).filter(name=name).first()
        if group and not group.user_set.using(db_alias).exists():
            group.delete(using=db_alias)


class Migration(migrations.Migration):

    dependencies = [("apk", "0009_apksubmission_review_assigned_at_and_more")]

    operations = [migrations.RunPython(create_groups, remove_groups)]
