"""APK ishining holat o'tishlari.

Oqim: Yangi -> (kursant oladi) -> Kursant tahlil qilmoqda -> (Chilonzorga yuboradi)
-> Chilonzor ko'rib chiqmoqda -> Qabul qilindi  YOKI  Qaytarildi (sabab bilan) ->
kursant tuzatib qayta yuboradi.

Har bir o'tish bitta tranzaksiyada, qator qulflanib bajariladi - ikki kursant bir
vaqtda bitta ishni ololmaydi."""

from django.db import transaction
from django.utils import timezone

from app.ui_i18n import translate

from .models import ApkEvent, ApkFinding, ApkSubmission
from .notifications import notify_group, notify_user
from .permissions import (
    GROUP_CHILONZOR_ADMINS,
    chilonzor_admin_group_for,
    user_is_chilonzor_super_admin,
    user_is_chilonzor_worker,
)


class WorkflowError(Exception):
    """Foydalanuvchiga ko'rsatiladigan o'tish xatosi."""


def _lock(submission_id):
    return ApkSubmission.objects.select_for_update().get(pk=submission_id)


def _log(submission, actor, action, note="", review_assignee=None):
    ApkEvent.objects.create(
        submission=submission,
        actor=actor,
        action=action,
        note=note,
        review_assignee=review_assignee,
    )


def record_received(submission):
    _log(submission, submission.source, ApkEvent.ACTION_RECEIVED)


def record_finding_deleted(submission, finding, actor_profile):
    _log(
        submission,
        actor_profile,
        ApkEvent.ACTION_FINDING_DELETED,
        f"{finding.kind}: {finding.value}",
    )


def record_analysis_note(submission, actor_profile, note):
    _log(
        submission,
        actor_profile,
        ApkEvent.ACTION_ANALYSIS_NOTE,
        note or translate("Tahlil izohi tozalandi."),
    )


def _ensure_owner(submission, actor_profile, is_staff):
    if is_staff:
        return
    if submission.assigned_to_id != actor_profile.pk:
        raise WorkflowError(translate("Bu ish sizga biriktirilmagan."))


def claim(submission_id, kursant_profile):
    with transaction.atomic():
        submission = _lock(submission_id)
        if submission.status != ApkSubmission.STATUS_NEW or submission.assigned_to_id:
            if submission.assigned_to_id == kursant_profile.pk:
                raise WorkflowError(translate("Bu ish allaqachon sizga biriktirilgan."))
            raise WorkflowError(
                translate(
                    "Bu ishni boshqa kursant olgan: {officer}.",
                    officer=str(submission.assigned_to or "-"),
                )
            )
        submission.assigned_to = kursant_profile
        submission.claimed_at = timezone.now()
        submission.status = ApkSubmission.STATUS_IN_PROGRESS
        submission.save(update_fields=["assigned_to", "claimed_at", "status", "updated_at"])
        _log(submission, kursant_profile, ApkEvent.ACTION_CLAIMED)
    return submission


def release(submission_id, actor_profile, is_staff=False):
    """Kursant ishni bo'shatadi - ish yana "Yangi" bo'ladi, topilmalar saqlanadi."""
    with transaction.atomic():
        submission = _lock(submission_id)
        _ensure_owner(submission, actor_profile, is_staff)
        if submission.status not in ApkSubmission.EDITABLE_STATUSES:
            raise WorkflowError(translate("Bu bosqichda ishni qaytarib bo'lmaydi."))
        submission.assigned_to = None
        submission.claimed_at = None
        submission.status = ApkSubmission.STATUS_NEW
        submission.save(update_fields=["assigned_to", "claimed_at", "status", "updated_at"])
        _log(submission, actor_profile, ApkEvent.ACTION_RELEASED)
    return submission


def send_to_chilonzor(submission_id, actor_profile, is_staff=False):
    with transaction.atomic():
        submission = _lock(submission_id)
        _ensure_owner(submission, actor_profile, is_staff)
        if submission.status not in ApkSubmission.EDITABLE_STATUSES:
            raise WorkflowError(translate("Bu ish hozir yuborib bo'lmaydigan holatda."))
        if not ApkFinding.objects.filter(submission=submission).exists():
            raise WorkflowError(
                translate("Yuborishdan oldin kamida bitta IP, domen yoki Telegram ID kiriting.")
            )
        submission.status = ApkSubmission.STATUS_SENT
        submission.sent_at = timezone.now()
        submission.review_assigned_to = None
        submission.review_assigned_at = None
        submission.save(
            update_fields=[
                "status", "sent_at", "review_assigned_to", "review_assigned_at", "updated_at"
            ]
        )
        _log(submission, actor_profile, ApkEvent.ACTION_SENT)

    notify_group(
        actor_profile,
        GROUP_CHILONZOR_ADMINS,
        translate(
            "#{id} {file} Chilonzor xodimiga biriktirishni kutmoqda.",
            id=submission.pk,
            file=submission.file_name,
        ),
    )
    return submission


def assign_review(submission_id, reviewer_profile, actor_profile):
    if (
        not reviewer_profile.account_id
        or not reviewer_profile.account.is_active
        or not user_is_chilonzor_worker(reviewer_profile.account)
    ):
        raise WorkflowError(translate("Faqat faol Chilonzor xodimiga ish biriktirish mumkin."))
    actor_account = actor_profile.account if actor_profile else None
    manager_group = chilonzor_admin_group_for(actor_account) if actor_account else None
    is_super_admin = bool(actor_account and user_is_chilonzor_super_admin(actor_account))
    if not is_super_admin and not manager_group:
        raise WorkflowError(translate("Faqat Chilonzor admin ishni xodimga biriktira oladi."))
    if manager_group and reviewer_profile.chilonzor_manager_id != actor_profile.pk:
        raise WorkflowError(translate("Faqat o'z jamoangizdagi xodimga ish biriktira olasiz."))
    with transaction.atomic():
        submission = _lock(submission_id)
        if submission.status != ApkSubmission.STATUS_SENT:
            raise WorkflowError(translate("Faqat Chilonzorga yuborilgan ishni biriktirish mumkin."))
        if submission.review_assigned_to_id == reviewer_profile.pk:
            raise WorkflowError(translate("Bu ish allaqachon ushbu xodimga biriktirilgan."))
        previous_reviewer = submission.review_assigned_to
        if (
            manager_group
            and previous_reviewer
            and previous_reviewer.chilonzor_manager_id != actor_profile.pk
        ):
            raise WorkflowError(translate("Boshqa jamoaga biriktirilgan ishni o'zgartira olmaysiz."))
        submission.review_assigned_to = reviewer_profile
        submission.review_assigned_at = timezone.now()
        submission.save(update_fields=["review_assigned_to", "review_assigned_at", "updated_at"])
        note = (
            f"{previous_reviewer} -> {reviewer_profile}"
            if previous_reviewer
            else str(reviewer_profile)
        )
        _log(
            submission,
            actor_profile,
            ApkEvent.ACTION_REVIEW_ASSIGNED,
            note,
            review_assignee=reviewer_profile,
        )

    notify_user(
        actor_profile,
        reviewer_profile,
        translate(
            "#{id} {file} sizga Chilonzor ko'rib chiqishi uchun biriktirildi.",
            id=submission.pk,
            file=submission.file_name,
        ),
    )
    return submission


def accept(submission_id, reviewer_profile, note="", is_staff=False):
    with transaction.atomic():
        submission = _lock(submission_id)
        if submission.status != ApkSubmission.STATUS_SENT:
            raise WorkflowError(translate("Bu ish ko'rib chiqish holatida emas."))
        if not is_staff and submission.review_assigned_to_id != reviewer_profile.pk:
            raise WorkflowError(translate("Bu ish Chilonzor xodimi sifatida sizga biriktirilmagan."))
        submission.status = ApkSubmission.STATUS_ACCEPTED
        submission.reviewed_by = reviewer_profile
        submission.reviewed_at = timezone.now()
        submission.review_note = note
        submission.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"]
        )
        _log(submission, reviewer_profile, ApkEvent.ACTION_ACCEPTED, note)

    notify_user(
        reviewer_profile,
        submission.assigned_to,
        translate(
            "#{id} {file} bo'yicha tahlilingiz qabul qilindi.",
            id=submission.pk,
            file=submission.file_name,
        ),
    )
    return submission


def send_back(submission_id, reviewer_profile, note, is_staff=False):
    note = (note or "").strip()
    if not note:
        raise WorkflowError(translate("Qaytarish sababini (kamchiliklarni) yozish shart."))
    with transaction.atomic():
        submission = _lock(submission_id)
        if submission.status != ApkSubmission.STATUS_SENT:
            raise WorkflowError(translate("Bu ish ko'rib chiqish holatida emas."))
        if not is_staff and submission.review_assigned_to_id != reviewer_profile.pk:
            raise WorkflowError(translate("Bu ish Chilonzor xodimi sifatida sizga biriktirilmagan."))
        submission.status = ApkSubmission.STATUS_RETURNED
        submission.reviewed_by = reviewer_profile
        submission.reviewed_at = timezone.now()
        submission.review_note = note
        submission.return_count += 1
        submission.save(
            update_fields=[
                "status", "reviewed_by", "reviewed_at", "review_note", "return_count",
                "updated_at",
            ]
        )
        _log(submission, reviewer_profile, ApkEvent.ACTION_RETURNED, note)

    notify_user(
        reviewer_profile,
        submission.assigned_to,
        translate(
            "#{id} {file} qaytarildi. Kamchiliklar: {note}",
            id=submission.pk,
            file=submission.file_name,
            note=note,
        ),
    )
    return submission


def add_findings(submission, kind, values, actor_profile):
    """Yangi qiymatlarni qo'shadi, allaqachon borlarini o'tkazib yuboradi. Qo'shilganlar sonini qaytaradi."""
    existing = set(
        ApkFinding.objects.filter(submission=submission, kind=kind).values_list("value", flat=True)
    )
    new_rows = [
        ApkFinding(submission=submission, kind=kind, value=value, added_by=actor_profile)
        for value in values
        if value not in existing
    ]
    ApkFinding.objects.bulk_create(new_rows)
    if new_rows:
        _log(
            submission,
            actor_profile,
            ApkEvent.ACTION_FINDINGS_ADDED,
            "\n".join(f"{kind}: {row.value}" for row in new_rows),
        )
    return len(new_rows)
