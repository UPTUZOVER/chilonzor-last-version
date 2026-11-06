"""OSINT topshiriqlarini kursant va operator orasida yuritish."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from app.ui_i18n import translate

from .models import Kursant, OsintTask, OsintTaskResult
from .notifications import notify_group, notify_user
from .permissions import GROUP_CHILONZOR_OPER


class OsintWorkflowError(Exception):
    """OSINT topshirig'ining joriy holatida amal bajarib bo'lmaydi."""


def claim_by_student(task_id, student_profile):
    updated = OsintTask.objects.filter(
        pk=task_id,
        status=OsintTask.STATUS_NEW,
        student__isnull=True,
    ).update(
        student=student_profile,
        student_claimed_at=timezone.now(),
        status=OsintTask.STATUS_STUDENT_WORKING,
    )
    if not updated:
        raise OsintWorkflowError(translate("Bu topshiriqni boshqa kursant olgan yoki u boshlangan."))
    return OsintTask.objects.get(pk=task_id)


def submit_by_student(task_id, student_profile, pairs):
    with transaction.atomic():
        updated = OsintTask.objects.filter(
            pk=task_id,
            student=student_profile,
            status__in=(OsintTask.STATUS_STUDENT_WORKING, OsintTask.STATUS_RETURNED),
        ).update(
            status=OsintTask.STATUS_SENT,
            student_submitted_at=timezone.now(),
            operator=None,
            operator_claimed_at=None,
            return_note="",
        )
        if not updated:
            raise OsintWorkflowError(
                translate("Bu topshiriq sizga biriktirilmagan yoki yuborib bo'lmaydi.")
            )

        task = OsintTask.objects.get(pk=task_id)
        task.results.all().delete()
        OsintTaskResult.objects.bulk_create(
            [OsintTaskResult(task=task, order=index, **pair) for index, pair in enumerate(pairs)]
        )

    notify_group(
        student_profile,
        GROUP_CHILONZOR_OPER,
        translate(
            "OSINT kursant {student} topshiriqni ko'rib chiqish uchun yubordi: {title}.",
            student=student_profile,
            title=task.title,
        ),
    )
    return task


def claim_by_operator(task_id, operator_profile):
    updated = OsintTask.objects.filter(
        pk=task_id,
        status=OsintTask.STATUS_SENT,
        operator__isnull=True,
    ).update(
        operator=operator_profile,
        operator_claimed_at=timezone.now(),
        status=OsintTask.STATUS_OPERATOR_WORKING,
    )
    if not updated:
        raise OsintWorkflowError(
            translate("Bu topshiriqni boshqa operator olgan yoki u ko'rib chiqilmayapti.")
        )
    return OsintTask.objects.get(pk=task_id)


def accept_by_operator(task_id, operator_profile, useful):
    if not useful:
        raise OsintWorkflowError(translate("Tasdiqlashdan oldin ma'lumot foydali ekanini belgilang."))

    with transaction.atomic():
        task = OsintTask.objects.filter(pk=task_id).only("student_id").first()
        kursant = (
            Kursant.objects.filter(user_id=task.student_id, kind=Kursant.TYPE_OSINT)
            .only("pk")
            .first()
            if task and task.student_id
            else None
        )
        if kursant is None:
            raise OsintWorkflowError(translate("OSINT kursant profili topilmadi."))

        updated = OsintTask.objects.filter(
            pk=task_id,
            status=OsintTask.STATUS_OPERATOR_WORKING,
            operator=operator_profile,
            points_awarded=False,
        ).update(
            status=OsintTask.STATUS_ACCEPTED,
            reviewed_by=operator_profile,
            reviewed_at=timezone.now(),
            points_awarded=True,
            return_note="",
        )
        if not updated:
            raise OsintWorkflowError(
                translate("Bu topshiriqni tasdiqlash uchun sizga biriktirilmagan.")
            )

        awarded = Kursant.objects.filter(pk=kursant.pk).update(
            osint_points=F("osint_points") + 10
        )
        if not awarded:
            raise OsintWorkflowError(translate("OSINT kursant profili topilmadi."))
        task = OsintTask.objects.select_related("student").get(pk=task_id)

    notify_user(
        operator_profile,
        task.student,
        translate("{title} topshirig'ingiz tasdiqlandi. Sizga 10 ball berildi.", title=task.title),
    )
    return task


def return_to_student(task_id, operator_profile, note):
    note = (note or "").strip()
    if not note:
        raise OsintWorkflowError(translate("Qaytarish sababini yozing."))

    with transaction.atomic():
        updated = OsintTask.objects.filter(
            pk=task_id,
            status=OsintTask.STATUS_OPERATOR_WORKING,
            operator=operator_profile,
        ).update(
            status=OsintTask.STATUS_RETURNED,
            reviewed_by=operator_profile,
            reviewed_at=timezone.now(),
            return_note=note,
            operator=None,
            operator_claimed_at=None,
        )
        if not updated:
            raise OsintWorkflowError(translate("Bu topshiriq sizga biriktirilmagan."))
        task = OsintTask.objects.select_related("student").get(pk=task_id)

    notify_user(
        operator_profile,
        task.student,
        translate("{title} topshirig'i tuzatish uchun qaytarildi.", title=task.title),
    )
    return task
