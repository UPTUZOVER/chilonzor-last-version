"""Telegram uslubidagi ichki chat.

Uch xil suhbat bor:
  - shaxsiy suhbat: istalgan ikki foydalanuvchi orasida (matn, rasm, fayl, audio);
  - "Bildirishnomalar": ish jarayonidan avtomatik xabarlar (AdminMessage.is_system);
  - "E'lonlar": hammaga yuborilgan xabarlar, faqat admin yozadi.

Fayllar ochiq /media/ orqali berilmaydi: message_attachment_view faqat suhbat
ishtirokchisiga beradi. Rasm va audio brauzerda ochiladi, qolganlari yuklab olinadi.
"""

import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import AdminMessage, MessageReaction, Users
from .ui_i18n import translate
from .views import account_has_group, get_or_create_profile, get_role_label_for_account

MAX_ATTACHMENT_MB = 25
MAX_BODY_LENGTH = 4000
THREAD_LIMIT = 150
SEND_LIMIT_PER_MINUTE = 40

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
AUDIO_TYPES = {
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".webm": "audio/webm",
}

QUICK_REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🔥", "👏", "✅"]
EMOJI_SET = [
    "😀", "😁", "😂", "🤣", "😊", "😇", "🙂", "😉", "😍", "😘", "😎", "🤔",
    "🤨", "😐", "🙄", "😏", "😴", "😮", "😲", "😢", "😭", "😤", "😡", "🤯",
    "😱", "🥳", "🤝", "👍", "👎", "👌", "✌️", "🤞", "👏", "🙏", "💪", "👋",
    "✋", "☝️", "👀", "❤️", "💔", "🔥", "⭐", "✨", "🎉", "✅", "❌", "⚠️",
    "❗", "❓", "💯", "📌", "📎", "📷", "🎤", "📁", "🔒", "🔍", "🚀", "⏰",
]


# --------------------------------------------------------------------------
# Yordamchilar
# --------------------------------------------------------------------------


def _news_visible(user):
    # MVD xodimlari umumiy e'lonlarni ko'rmaydi (avvalgi qoida saqlandi).
    return user.is_staff or not account_has_group(user, "MVD")


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _attachment_kind(filename):
    extension = os.path.splitext(filename or "")[1].lower()
    if extension in IMAGE_TYPES:
        return AdminMessage.ATTACHMENT_IMAGE
    if extension in AUDIO_TYPES:
        return AdminMessage.ATTACHMENT_AUDIO
    return AdminMessage.ATTACHMENT_FILE


def _preview(message):
    if message is None:
        return ""
    if message.body:
        return message.body.replace("\n", " ")[:80]
    return {
        AdminMessage.ATTACHMENT_IMAGE: "📷 " + translate("Rasm"),
        AdminMessage.ATTACHMENT_AUDIO: "🎤 " + translate("Audio xabar"),
    }.get(message.attachment_kind, "📎 " + (message.attachment_name or translate("Fayl")))


def _resolve_thread(request, me, key):
    """'news' | 'system' | profil id -> (kind, peer). Ruxsat bo'lmasa Http404."""
    if key == "news":
        if not _news_visible(request.user):
            raise Http404
        return "news", None
    if key == "system":
        return "system", None
    try:
        peer = Users.objects.select_related("account").get(pk=int(key), account__isnull=False)
    except (TypeError, ValueError, Users.DoesNotExist):
        raise Http404 from None
    if peer.pk == me.pk:
        raise Http404
    return "direct", peer


def _thread_key(kind, peer):
    return str(peer.pk) if kind == "direct" else kind


def _thread_queryset(me, kind, peer=None):
    base = AdminMessage.objects.select_related("sender", "sender__account").prefetch_related("reactions__user")
    if kind == "news":
        return base.filter(recipient__isnull=True)
    if kind == "system":
        return base.filter(recipient=me, is_system=True)
    return base.filter(is_system=False).filter(
        Q(sender=me, recipient=peer) | Q(sender=peer, recipient=me)
    )


def _mark_read(me, kind, peer=None):
    now = timezone.now()
    if kind == "news":
        me.messages_last_read_at = now
        me.save(update_fields=["messages_last_read_at"])
    elif kind == "system":
        AdminMessage.objects.filter(recipient=me, is_system=True, read_at__isnull=True).update(read_at=now)
    elif kind == "direct":
        AdminMessage.objects.filter(
            recipient=me, sender=peer, is_system=False, read_at__isnull=True
        ).update(read_at=now)


def _decorate(items, me):
    """Har xabarga: o'zimnikimi va reaksiyalar guruhi (emoji, soni, men qo'yganmi, kimlar)."""
    for item in items:
        item.is_mine = item.sender_id == me.pk
        groups = {}
        for reaction in item.reactions.all():
            group = groups.setdefault(reaction.emoji, {"emoji": reaction.emoji, "count": 0, "mine": False, "names": []})
            group["count"] += 1
            group["mine"] = group["mine"] or reaction.user_id == me.pk
            group["names"].append(str(reaction.user))
        item.reaction_groups = list(groups.values())
    return items


def _accessible_message(request, me, message_id):
    message = get_object_or_404(
        AdminMessage.objects.select_related("sender", "sender__account").prefetch_related("reactions__user"),
        pk=message_id,
    )
    if message.recipient_id is None:
        if _news_visible(request.user):
            return message
    elif me.pk in (message.sender_id, message.recipient_id):
        return message
    raise Http404


def _conversations(request, me):
    """Chap panel: E'lonlar, Bildirishnomalar va shaxsiy suhbatlar (eng yangisi tepada)."""
    items = []
    if _news_visible(request.user):
        last = AdminMessage.objects.filter(recipient__isnull=True).select_related("sender").order_by("-created_at", "-id").first()
        items.append({
            "key": "news", "kind": "news", "title": translate("E'lonlar"), "url": reverse("app:message_news"),
            "last": last, "preview": _preview(last), "unread": me.unread_news_queryset().count(),
        })
    system = AdminMessage.objects.filter(recipient=me, is_system=True)
    last = system.order_by("-created_at", "-id").first()
    items.append({
        "key": "system", "kind": "system", "title": translate("Bildirishnomalar"), "url": reverse("app:message_system"),
        "last": last, "preview": _preview(last), "unread": system.filter(read_at__isnull=True).count(),
    })

    direct = (
        AdminMessage.objects.filter(is_system=False, recipient__isnull=False)
        .filter(Q(sender=me) | Q(recipient=me))
        .select_related("sender", "sender__account", "recipient", "recipient__account")
        .order_by("-created_at", "-id")[:600]
    )
    unread_by_sender = dict(
        AdminMessage.objects.filter(recipient=me, is_system=False, read_at__isnull=True)
        .values_list("sender")
        .annotate(total=Count("id"))
    )
    seen = set()
    for message in direct:
        peer = message.recipient if message.sender_id == me.pk else message.sender
        if peer is None or peer.pk in seen:
            continue
        seen.add(peer.pk)
        preview = _preview(message)
        if message.sender_id == me.pk:
            preview = translate("Siz") + ": " + preview
        items.append({
            "key": str(peer.pk), "kind": "direct", "title": str(peer), "peer": peer,
            "url": reverse("app:message_thread", args=[peer.pk]), "last": message, "preview": preview,
            "unread": unread_by_sender.get(peer.pk, 0),
        })
    return items


def _contacts(me, exclude_ids=()):
    users = (
        Users.objects.select_related("account")
        .prefetch_related("account__groups")
        .filter(account__isnull=False, account__is_active=True)
        .exclude(pk=me.pk)
        .exclude(pk__in=exclude_ids)
        .order_by("first_name", "last_name", "pk")
    )
    return [
        {"profile": user, "role": get_role_label_for_account(user.account), "username": user.account.username}
        for user in users
    ]


def _render_messages(request, items, kind):
    return render_to_string(
        "app/_chat_messages.html",
        {"thread_messages": items, "thread_kind": kind, "quick_reactions": QUICK_REACTIONS},
        request=request,
    )


def _render_reactions(request, item, kind):
    return render_to_string("app/_chat_reactions.html", {"item": item, "thread_kind": kind}, request=request)


def _render_conversations(request, me, active_key):
    return render_to_string(
        "app/_chat_conversations.html",
        {"conversations": _conversations(request, me), "active_key": active_key},
        request=request,
    )


def _unread_total(request, me):
    return me.unread_message_count(include_news=_news_visible(request.user))


# --------------------------------------------------------------------------
# Sahifalar
# --------------------------------------------------------------------------


@login_required
def message_inbox_view(request, pk=None, channel=None):
    me = get_or_create_profile(request.user)
    request._message_profile = me
    key = channel or (str(pk) if pk is not None else None)
    kind, peer, items = None, None, []
    if key:
        kind, peer = _resolve_thread(request, me, key)
        _mark_read(me, kind, peer)
        items = list(_thread_queryset(me, kind, peer).order_by("-created_at", "-id")[:THREAD_LIMIT])[::-1]
        _decorate(items, me)

    if kind == "news":
        title, subtitle = translate("E'lonlar"), translate("Administrator e'lonlari hammaga yuboriladi")
    elif kind == "system":
        title, subtitle = translate("Bildirishnomalar"), translate("Ish jarayonidan avtomatik xabarlar")
    elif kind == "direct":
        title, subtitle = str(peer), f"{get_role_label_for_account(peer.account)} · @{peer.account.username}"
    else:
        title, subtitle = "", ""

    active_key = _thread_key(kind, peer) if kind else ""
    conversations = _conversations(request, me)
    return render(
        request,
        "app/messages.html",
        {
            "conversations": conversations,
            "contacts": _contacts(me, [item["peer"].pk for item in conversations if item["kind"] == "direct"]),
            "thread_kind": kind,
            "thread_key": active_key,
            "active_key": active_key,
            "thread_peer": peer,
            "thread_title": title,
            "thread_subtitle": subtitle,
            "thread_messages": items,
            "can_post": kind == "direct" or (kind == "news" and request.user.is_staff),
            "quick_reactions": QUICK_REACTIONS,
            "emoji_set": EMOJI_SET,
            "max_attachment_mb": MAX_ATTACHMENT_MB,
        },
    )


@login_required
@require_POST
def message_send_view(request):
    me = get_or_create_profile(request.user)
    key = request.POST.get("to") or ""

    def fail(text, status=400):
        if _is_ajax(request):
            return JsonResponse({"error": text}, status=status)
        messages.error(request, text)
        return redirect("app:message_inbox")

    # Daqiqasiga yuborish chegarasi (spamdan himoya).
    from django.core.cache import cache

    cache_key = f"chat_send_{request.user.pk}"
    cache.add(cache_key, 0, 60)
    try:
        sent = cache.incr(cache_key)
    except ValueError:
        sent = 1
    if sent > SEND_LIMIT_PER_MINUTE:
        return fail(translate("Juda tez yuboryapsiz. Bir oz kuting."), status=429)

    try:
        kind, peer = _resolve_thread(request, me, key)
    except Http404:
        return fail(translate("Suhbat topilmadi."), status=404)
    if kind == "system" or (kind == "news" and not request.user.is_staff):
        return fail(translate("Bu kanalga yozish mumkin emas."), status=403)

    body = (request.POST.get("body") or "").strip()[:MAX_BODY_LENGTH]
    upload = request.FILES.get("attachment")
    if not body and not upload:
        return fail(translate("Xabar matni yoki fayl kerak."))
    if upload and upload.size > MAX_ATTACHMENT_MB * 1024 * 1024:
        return fail(translate("Fayl hajmi {size} MB dan oshmasligi kerak.", size=MAX_ATTACHMENT_MB))

    message = AdminMessage(sender=me, recipient=peer, body=body, is_system=False)
    if upload:
        name = os.path.basename(upload.name or "fayl")[:255]
        message.attachment_name = name
        message.attachment_kind = _attachment_kind(name)
        message.attachment_size = upload.size
        message.attachment.save(name, upload, save=False)
    message.save()

    if _is_ajax(request):
        message = _thread_queryset(me, kind, peer).get(pk=message.pk)
        _decorate([message], me)
        return JsonResponse({"id": message.pk, "html": _render_messages(request, [message], kind)})
    return redirect(reverse("app:message_news") if kind == "news" else reverse("app:message_thread", args=[peer.pk]))


@login_required
@require_GET
def message_poll_view(request):
    """Ochiq suhbat uchun yangi xabarlar, reaksiya va o'qilganlik holati, chap panel."""
    me = get_or_create_profile(request.user)
    key = request.GET.get("thread") or ""
    data = {"unread_total": 0, "html": "", "state": {}, "ids": []}
    if key:
        kind, peer = _resolve_thread(request, me, key)
        try:
            after = int(request.GET.get("after") or 0)
        except ValueError:
            after = 0
        queryset = _thread_queryset(me, kind, peer)
        new_items = _decorate(list(queryset.filter(id__gt=after).order_by("created_at", "id")[:50]), me)
        if new_items:
            _mark_read(me, kind, peer)
        recent = _decorate(list(queryset.order_by("-created_at", "-id")[:60]), me)
        data["html"] = _render_messages(request, new_items, kind) if new_items else ""
        data["ids"] = [item.pk for item in recent]
        data["state"] = {
            item.pk: {"reactions": _render_reactions(request, item, kind), "read": bool(item.read_at)}
            for item in recent
        }
        active_key = _thread_key(kind, peer)
    else:
        active_key = ""
    data["conversations"] = _render_conversations(request, me, active_key)
    data["unread_total"] = _unread_total(request, me)
    return JsonResponse(data)


@login_required
@require_POST
def message_react_view(request, message_id):
    me = get_or_create_profile(request.user)
    message = _accessible_message(request, me, message_id)
    emoji = request.POST.get("emoji") or ""
    if emoji not in QUICK_REACTIONS or message.is_system:
        return JsonResponse({"error": translate("Bu reaksiya mavjud emas.")}, status=400)
    existing = MessageReaction.objects.filter(message=message, user=me).first()
    if existing and existing.emoji == emoji:
        existing.delete()
    elif existing:
        existing.emoji = emoji
        existing.save(update_fields=["emoji"])
    else:
        MessageReaction.objects.create(message=message, user=me, emoji=emoji)
    message = _accessible_message(request, me, message_id)
    _decorate([message], me)
    kind = "news" if message.recipient_id is None else "direct"
    return JsonResponse({"html": _render_reactions(request, message, kind)})


@login_required
@require_POST
def message_delete_view(request, message_id):
    me = get_or_create_profile(request.user)
    message = _accessible_message(request, me, message_id)
    if message.sender_id != me.pk or message.is_system:
        raise Http404
    if message.attachment:
        message.attachment.delete(save=False)
    message.delete()
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect(request.META.get("HTTP_REFERER") or reverse("app:message_inbox"))


@login_required
def message_attachment_view(request, message_id):
    me = get_or_create_profile(request.user)
    message = _accessible_message(request, me, message_id)
    if not message.attachment:
        raise Http404
    extension = os.path.splitext(message.attachment_name)[1].lower()
    inline_type = IMAGE_TYPES.get(extension) or AUDIO_TYPES.get(extension)
    inline = bool(inline_type) and not request.GET.get("download")
    try:
        handle = message.attachment.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    response = FileResponse(
        handle,
        as_attachment=not inline,
        filename=message.attachment_name,
        content_type=inline_type if inline else "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; media-src 'self'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response
