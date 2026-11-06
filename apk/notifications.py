"""APK bo'limi ichida tizim xabarlarini (AdminMessage) yuborish."""

from django.db.models import Q

from app.models import AdminMessage, Users


def notify_group(sender_profile, group_name, body):
    """Guruhdagi har bir faol foydalanuvchiga tizim ichi xabar yuboradi."""
    group_names = (group_name,) if isinstance(group_name, str) else tuple(group_name)
    if not group_names:
        return 0
    group_filter = Q()
    for name in group_names:
        group_filter |= Q(account__groups__name__iexact=name)
    recipients = list(
        Users.objects.filter(
            group_filter, account__is_active=True
        ).distinct()
    )
    if sender_profile:
        recipients = [item for item in recipients if item.pk != sender_profile.pk]
    if not recipients:
        return 0
    AdminMessage.objects.bulk_create(
        [
            AdminMessage(sender=sender_profile, recipient=recipient, body=body)
            for recipient in recipients
        ]
    )
    return len(recipients)


def notify_user(sender_profile, recipient_profile, body):
    if not recipient_profile or (sender_profile and recipient_profile.pk == sender_profile.pk):
        return
    AdminMessage.objects.create(sender=sender_profile, recipient=recipient_profile, body=body)
