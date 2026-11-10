import os
import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from .ui_i18n import translate

User = get_user_model()


class Users(models.Model):
    """Django akkauntiga bog'langan profil (ism-familiya va xabarlar holati)."""

    account = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        blank=True,
        null=True,
    )
    chilonzor_manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="chilonzor_employees",
        blank=True,
        null=True,
        verbose_name=translate("Chilonzor mas'ul admini"),
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    messages_last_read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        if full_name:
            return full_name
        if self.account:
            return self.account.username
        return translate("Foydalanuvchi {pk}", pk=self.pk)

    def unread_direct_queryset(self):
        """Shaxsan menga kelgan (suhbat va bildirishnoma) o'qilmagan xabarlar."""
        return AdminMessage.objects.filter(recipient=self, read_at__isnull=True).exclude(sender=self)

    def unread_news_queryset(self):
        """Hammaga yuborilgan e'lonlardan oxirgi ko'rishdan keyin kelganlari."""
        queryset = AdminMessage.objects.filter(recipient__isnull=True).exclude(sender=self)
        if self.messages_last_read_at:
            queryset = queryset.filter(created_at__gt=self.messages_last_read_at)
        return queryset

    def unread_message_count(self, include_news=True):
        count = self.unread_direct_queryset().count()
        if include_news:
            count += self.unread_news_queryset().count()
        return count


def chat_upload_path(instance, filename):
    """Fayl nomi foydalanuvchidan olinmaydi: tasodifiy nom, asl kengaytma."""
    extension = os.path.splitext(filename)[1].lower()[:10]
    return f"chat/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class AdminMessage(models.Model):
    """Ichki xabar: shaxsiy suhbat, tizim bildirishnomasi yoki hammaga e'lon.

    - recipient bo'sh  -> hammaga e'lon (E'lonlar kanali);
    - is_system=True   -> ish jarayonidan avtomatik bildirishnoma;
    - qolganlari       -> ikki foydalanuvchi orasidagi suhbat.
    """

    ATTACHMENT_IMAGE = "image"
    ATTACHMENT_AUDIO = "audio"
    ATTACHMENT_FILE = "file"

    sender = models.ForeignKey(
        Users,
        on_delete=models.CASCADE,
        related_name="sent_messages",
        blank=True,
        null=True,
        help_text="Bo'sh bo'lsa - tizim tomonidan avtomatik yuborilgan xabar.",
    )
    recipient = models.ForeignKey(
        Users,
        on_delete=models.CASCADE,
        related_name="received_messages",
        blank=True,
        null=True,
    )
    body = models.TextField(blank=True)
    is_system = models.BooleanField(default=False, db_index=True)
    attachment = models.FileField(upload_to=chat_upload_path, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    attachment_kind = models.CharField(max_length=10, blank=True)
    attachment_size = models.PositiveIntegerField(default=0)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["recipient", "created_at"]),
            models.Index(fields=["sender", "created_at"]),
            models.Index(fields=["recipient", "read_at"]),
        ]

    def __str__(self):
        return f"{self.sender_display} -> {self.audience_label}"

    @property
    def is_broadcast(self):
        return self.recipient_id is None

    @property
    def sender_display(self):
        """Tizim o'zi (masalan, karta tasdiqlashga avtomatik yuborilganda)
        yuborgan xabarlarda `sender` bo'sh bo'ladi - shunda o'rniga shu
        matn ko'rsatiladi."""
        if self.sender_id:
            return str(self.sender)
        return translate("Tizim")

    @property
    def audience_label(self):
        if self.is_broadcast:
            return translate("Barcha foydalanuvchilar")
        return str(self.recipient)


class MessageReaction(models.Model):
    """Xabarga emoji reaksiya: har foydalanuvchi bitta xabarga bitta reaksiya."""

    message = models.ForeignKey(AdminMessage, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(Users, on_delete=models.CASCADE, related_name="message_reactions")
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["message", "user"], name="one_reaction_per_user"),
        ]

    def __str__(self):
        return f"{self.user} {self.emoji} #{self.message_id}"


class LoginBlock(models.Model):
    source_ip = models.CharField(max_length=64, unique=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(blank=True, null=True)
    blocked_until = models.DateTimeField(blank=True, null=True)
    last_username = models.CharField(max_length=150, blank=True)
    last_user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-last_attempt_at", "source_ip"]
        indexes = [
            models.Index(fields=["blocked_until"]),
        ]

    def __str__(self):
        return f"{self.source_ip} - {self.failed_attempts}"
