from django.db import migrations


GROUP_CHILONZOR = "Chilonzor"
GROUP_OPER = "chilonzor_oper"
GROUP_HUB = "chilonzor_hub"
MANAGER_GROUPS = (
    ("Chilonzor admin 02", GROUP_OPER),
    ("Chilonzor admin 03", GROUP_HUB),
)


def move_managed_workers(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")
    Users = apps.get_model("app", "Users")

    base_group, _ = Group.objects.using(db_alias).get_or_create(name=GROUP_CHILONZOR)
    groups = {
        name: Group.objects.using(db_alias).get_or_create(name=name)[0]
        for name in (GROUP_OPER, GROUP_HUB)
    }

    for manager_group_name, worker_group_name in MANAGER_GROUPS:
        manager_ids = User.objects.using(db_alias).filter(
            groups__name=manager_group_name
        ).values_list("pk", flat=True)
        profiles = Users.objects.using(db_alias).filter(
            chilonzor_manager__account_id__in=manager_ids,
            account__isnull=False,
        ).select_related("account")
        for profile in profiles:
            worker = profile.account
            worker.groups.remove(base_group, groups[GROUP_OPER], groups[GROUP_HUB])
            worker.groups.add(groups[worker_group_name])


def restore_generic_chilonzor_workers(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")
    Users = apps.get_model("app", "Users")

    base_group, _ = Group.objects.using(db_alias).get_or_create(name=GROUP_CHILONZOR)
    scoped_groups = Group.objects.using(db_alias).filter(name__in=(GROUP_OPER, GROUP_HUB))
    for manager_group_name, _worker_group_name in MANAGER_GROUPS:
        manager_ids = User.objects.using(db_alias).filter(
            groups__name=manager_group_name
        ).values_list("pk", flat=True)
        profiles = Users.objects.using(db_alias).filter(
            chilonzor_manager__account_id__in=manager_ids,
            account__isnull=False,
        ).select_related("account")
        for profile in profiles:
            profile.account.groups.remove(*scoped_groups)
            profile.account.groups.add(base_group)

    hub_group = Group.objects.using(db_alias).filter(name=GROUP_HUB).first()
    if hub_group and not hub_group.user_set.using(db_alias).exists():
        hub_group.delete(using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0002_users_chilonzor_manager"),
        ("apk", "0012_apkevent_review_assignee_alter_apkevent_action"),
    ]

    operations = [migrations.RunPython(move_managed_workers, restore_generic_chilonzor_workers)]
