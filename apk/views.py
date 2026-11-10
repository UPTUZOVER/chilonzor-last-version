"""APK tahlil bo'limi: botdan kelgan APK -> kursant tahlili -> Chilonzor qarori."""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from app.models import Users
from app.ui_i18n import translate

from . import workflow
from .dashboard_data import PERIOD_OPTIONS, build_dashboard_context, dashboard_role
from .forms import (
    AnalysisNoteForm,
    ApiClientForm,
    AttachChilonzorEmployeeForm,
    ChilonzorEmployeeForm,
    FindingsForm,
    KursantForm,
    OsintTaskForm,
    OsintTaskResultForm,
    ReviewAssignmentForm,
    ReviewForm,
)
from .models import (
    ApiClient,
    ApkEvent,
    ApkFinding,
    ApkSubmission,
    Kursant,
    OsintTask,
    OsintTaskResult,
    OsintTaskValue,
)
from . import osint_workflow
from .permissions import (
    GROUP_CHILONZOR,
    GROUP_CHILONZOR_ADMINS,
    GROUP_CHILONZOR_02_ADMIN,
    GROUP_CHILONZOR_03_ADMIN,
    GROUP_CHILONZOR_HUB,
    GROUP_CHILONZOR_OPER,
    deny,
    require_admin_or_redirect,
    require_apk_access_or_redirect,
    require_reviewer_or_redirect,
    require_worker_or_redirect,
    user_can_assign_chilonzor_review,
    chilonzor_admin_group_for,
    user_can_submit_osint_task,
    user_can_view_osint_tasks,
    user_can_review,
    user_can_work,
    user_has_apk_access,
    user_is_chilonzor,
    user_is_chilonzor_admin,
    user_is_chilonzor_super_admin,
    user_is_chilonzor_team_admin,
    user_is_chilonzor_worker,
    user_is_kursant,
    user_is_mvd,
    user_is_osint_kursant,
)

PAGE_SIZE = 50
# Chilonzor navbatida shundan uzoq kutgan ish kechikkan deb belgilanadi.
REVIEW_OVERDUE_HOURS = 48


def status_legend():
    """Rang izohi: har holat uchun rang + harf-kod + qisqa tushuntirish
    (holat faqat rang bilan berilmaydi)."""
    return [
        {
            "color": ApkSubmission.STATUS_COLORS[code],
            "code": ApkSubmission.STATUS_CODES[code],
            "label": str(label),
            "hint": str(ApkSubmission.STATUS_HINTS[code]),
        }
        for code, label in ApkSubmission.STATUS_CHOICES
    ]


def humanize_wait(delta):
    """timedelta -> "3 kun", "5 soat", "12 daqiqa"."""
    seconds = max(int(delta.total_seconds()), 0)
    if seconds >= 86400:
        return translate("{count} kun", count=seconds // 86400)
    if seconds >= 3600:
        return translate("{count} soat", count=seconds // 3600)
    return translate("{count} daqiqa", count=max(seconds // 60, 1))


# --------------------------------------------------------------------------
# Yordamchi funksiyalar
# --------------------------------------------------------------------------


def get_profile_for_user(user):
    profile = getattr(user, "profile", None)
    if profile is not None:
        return profile
    profile, _created = Users.objects.get_or_create(
        account=user,
        defaults={
            "first_name": user.first_name or user.username,
            "last_name": user.last_name,
        },
    )
    return profile


def chilonzor_review_workers():
    admin_profiles = Users.objects.filter(
        account__groups__name__in=GROUP_CHILONZOR_ADMINS
    ).values("pk")
    return (
        Users.objects.filter(account__is_active=True)
        .filter(
            Q(account__groups__name__iexact=GROUP_CHILONZOR)
            | Q(account__groups__name__iexact=GROUP_CHILONZOR_OPER)
            | Q(account__groups__name__iexact=GROUP_CHILONZOR_HUB)
        )
        .exclude(account__is_staff=True)
        .exclude(pk__in=admin_profiles)
        .select_related("account", "chilonzor_manager", "chilonzor_manager__account")
        .distinct()
        .order_by("first_name", "last_name", "account__username")
    )


def _can_open_chilonzor_review(user, profile, submission):
    if user_is_chilonzor_super_admin(user):
        return True
    if user_is_chilonzor_team_admin(user):
        return bool(
            (
                submission.status == ApkSubmission.STATUS_SENT
                and submission.review_assigned_to_id is None
            )
            or (
                submission.review_assigned_to_id is not None
                and submission.review_assigned_to.chilonzor_manager_id == profile.pk
            )
            or (
                submission.reviewed_by_id is not None
                and submission.reviewed_by.chilonzor_manager_id == profile.pk
            )
            or submission.events.filter(review_assignee__chilonzor_manager=profile).exists()
            or submission.events.filter(actor__chilonzor_manager=profile).exists()
            or submission.findings.filter(added_by__chilonzor_manager=profile).exists()
        )
    return bool(
        user_is_chilonzor_worker(user)
        and (
            submission.review_assigned_to_id == profile.pk
            or submission.reviewed_by_id == profile.pk
            or submission.events.filter(review_assignee=profile).exists()
            or submission.events.filter(actor=profile).exists()
            or submission.findings.filter(added_by=profile).exists()
        )
    )


def with_finding_counts(queryset):
    return queryset.annotate(
        ip_count=Count("findings", filter=Q(findings__kind=ApkFinding.KIND_IP), distinct=True),
        domain_count=Count(
            "findings", filter=Q(findings__kind=ApkFinding.KIND_DOMAIN), distinct=True
        ),
        telegram_count=Count(
            "findings", filter=Q(findings__kind=ApkFinding.KIND_TELEGRAM), distinct=True
        ),
    )


def search_filter(queryset, search):
    """Fayl nomi, SHA-256, yuboruvchi, guruh va topilmalar (IP/domen/Telegram ID) bo'yicha."""
    if not search:
        return queryset
    condition = (
        Q(file_name__icontains=search)
        | Q(sha256__istartswith=search)
        | Q(sender_name__icontains=search)
        | Q(sender_username__icontains=search)
        | Q(chat_title__icontains=search)
        | Q(findings__value__icontains=search)
    )
    if search.lstrip("-").isdigit():
        number = int(search)
        condition |= Q(sender_user_id=number) | Q(chat_id=number) | Q(pk=number)
    return queryset.filter(condition).distinct()


def status_filter_options(queryset=None):
    queryset = ApkSubmission.objects.all() if queryset is None else queryset
    counts = {
        row["status"]: row["count"]
        for row in queryset.values("status").annotate(count=Count("id"))
    }
    return [
        {"key": code, "label": str(label), "count": counts.get(code, 0)}
        for code, label in ApkSubmission.STATUS_CHOICES
    ]


def status_tabs(request, options, selected_status, total):
    """Ro'yxat ustidagi holat tablari: har holat soni va shu holatga filtr havolasi.
    Qidiruv va boshqa filtrlar saqlanadi, sahifa raqami esa tushib qoladi."""
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("holat", None)

    def url_for(key):
        query = params.copy()
        if key:
            query["holat"] = key
        encoded = query.urlencode()
        return f"?{encoded}" if encoded else request.path

    tabs = [
        {
            "key": "",
            "label": translate("Hammasi"),
            "count": total,
            "color": "",
            "url": url_for(""),
            "active": not selected_status,
        }
    ]
    for option in options:
        tabs.append(
            {
                **option,
                "color": ApkSubmission.STATUS_COLORS.get(option["key"], ""),
                "url": url_for(option["key"]),
                "active": option["key"] == selected_status,
            }
        )
    return tabs


# --------------------------------------------------------------------------
# Kirish nuqtasi
# --------------------------------------------------------------------------


@login_required
def home_view(request):
    blocked_response = require_apk_access_or_redirect(request)
    if blocked_response:
        return blocked_response

    user = request.user
    if user_is_chilonzor(user) and not user.is_staff and not user_is_kursant(user):
        return redirect("apk:review_queue")
    return redirect("apk:submission_list")


# --------------------------------------------------------------------------
# Asosiy jadval
# --------------------------------------------------------------------------


@login_required
def submission_list_view(request):
    blocked_response = require_apk_access_or_redirect(request)
    if blocked_response:
        return blocked_response

    profile = get_profile_for_user(request.user)
    search = (request.GET.get("q") or "").strip()
    selected_status = request.GET.get("holat") or ""
    selected_scope = request.GET.get("kim") or ""

    base = ApkSubmission.objects.all()
    is_chilonzor_worker = user_is_chilonzor_worker(request.user) and not request.user.is_staff
    if is_chilonzor_worker:
        base = base.filter(review_assigned_to=profile)
    elif user_is_chilonzor_team_admin(request.user) and not user_is_chilonzor_super_admin(request.user):
        base = base.filter(
            Q(status=ApkSubmission.STATUS_SENT, review_assigned_to__isnull=True)
            | Q(review_assigned_to__chilonzor_manager=profile)
            | Q(reviewed_by__chilonzor_manager=profile)
        )
    submissions = with_finding_counts(
        search_filter(base, search).select_related("assigned_to", "source")
    )
    if selected_status:
        submissions = submissions.filter(status=selected_status)
    if not is_chilonzor_worker and selected_scope == "mening":
        submissions = submissions.filter(assigned_to=profile)
    elif not is_chilonzor_worker and selected_scope == "bosh":
        submissions = submissions.filter(status=ApkSubmission.STATUS_NEW)
    elif is_chilonzor_worker:
        selected_scope = ""

    paginator = Paginator(submissions.order_by("-created_at", "-id"), PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    kursant_count = Kursant.objects.filter(
        is_active=True,
        kind=Kursant.TYPE_APK,
    ).count()

    my_count = base.filter(assigned_to=profile).count()
    new_count = base.filter(status=ApkSubmission.STATUS_NEW).count()
    filters = [
        {
            "name": "holat",
            "label": translate("Holat"),
            "options": status_filter_options(base),
            "selected": selected_status,
        }
    ]
    if not is_chilonzor_worker:
        filters.append(
            {
                "name": "kim",
                "label": translate("Kim"),
                "options": [
                    {"key": "mening", "label": translate("Mening ishlarim"), "count": my_count},
                    {"key": "bosh", "label": translate("Olinmaganlar"), "count": new_count},
                ],
                "selected": selected_scope,
            }
        )
    query = request.GET.copy()
    query.pop("page", None)
    total_count = base.count()

    return render(
        request,
        "apk/submission_list.html",
        {
            "submissions": page.object_list,
            "kursant_count": kursant_count,
            "page": page,
            "page_query": query.urlencode(),
            "legend": status_legend(),
            "search": search,
            "search_placeholder": translate(
                "Fayl, yuboruvchi, guruh, IP, domen yoki Telegram ID..."
            ),
            "filters": filters,
            "is_filtered": bool(search or selected_status or selected_scope),
            "result_count": paginator.count,
            "total_count": total_count,
            "status_tabs": status_tabs(request, filters[0]["options"], selected_status, total_count),
            "current_profile": profile,
            "can_work": user_can_work(request.user),
            "can_manage": request.user.is_staff,
        },
    )


# --------------------------------------------------------------------------
# APK ish sahifasi
# --------------------------------------------------------------------------


def _cross_reference_counts(submission, findings):
    """Har bir topilma boshqa nechta APK da ham uchragani: {(tur, qiymat): son}."""
    if not findings:
        return {}
    rows = (
        ApkFinding.objects.filter(value__in={item.value for item in findings})
        .exclude(submission=submission)
        .values("kind", "value")
        .annotate(count=Count("submission", distinct=True))
    )
    return {(row["kind"], row["value"]): row["count"] for row in rows}


def _detail_context(request, submission, **overrides):
    profile = get_profile_for_user(request.user)
    can_work = user_can_work(request.user)
    is_owner = submission.assigned_to_id == profile.pk
    can_edit = bool(
        can_work
        and submission.is_editable
        and (request.user.is_staff or is_owner)
    )
    can_claim = bool(
        can_work
        and submission.status == ApkSubmission.STATUS_NEW
        and not submission.assigned_to_id
        and user_is_kursant(request.user)
    )
    can_review = bool(
        submission.status == ApkSubmission.STATUS_SENT
        and (
            request.user.is_staff
            or (
                user_is_chilonzor_worker(request.user)
                and submission.review_assigned_to_id == profile.pk
            )
        )
    )
    can_assign_review = bool(
        user_can_assign_chilonzor_review(request.user)
        and submission.status == ApkSubmission.STATUS_SENT
    )
    review_workers = Users.objects.none()
    if can_assign_review:
        review_workers = chilonzor_review_workers()
        if user_is_chilonzor_team_admin(request.user) and not user_is_chilonzor_super_admin(request.user):
            review_workers = review_workers.filter(chilonzor_manager=profile)

    findings = list(submission.findings.select_related("added_by"))
    cross = _cross_reference_counts(submission, findings)
    groups = []
    for kind, label in ApkFinding.KIND_CHOICES:
        items = []
        for finding in findings:
            if finding.kind == kind:
                finding.other_count = cross.get((finding.kind, finding.value), 0)
                items.append(finding)
        groups.append({"kind": kind, "label": label, "items": items})

    if submission.is_link:
        same_source_submissions = ApkSubmission.objects.filter(
            source_type=ApkSubmission.SOURCE_LINK, source_url=submission.source_url
        ).exclude(pk=submission.pk).order_by("created_at")
    else:
        same_source_submissions = ApkSubmission.objects.filter(
            source_type=ApkSubmission.SOURCE_APK, sha256=submission.sha256
        ).exclude(pk=submission.pk).order_by("created_at")
    same_file_count = (
        ApkFinding.objects.filter(submission__in=same_source_submissions).count()
        if submission.duplicate_of_id
        else 0
    )

    context = {
        "submission": submission,
        "finding_groups": groups,
        "finding_total": len(findings),
        "events": submission.events.select_related("actor", "review_assignee"),
        "same_file_submissions": same_source_submissions,
        "same_file_finding_count": same_file_count,
        "is_owner": is_owner,
        "can_edit": can_edit,
        "can_claim": can_claim,
        "can_review": can_review,
        "can_assign_review": can_assign_review,
        "review_workers": review_workers,
        "review_assignment_form": ReviewAssignmentForm(
            reviewers=review_workers,
            initial={"reviewer": submission.review_assigned_to_id},
        ),
        "can_manage": request.user.is_staff,
        "findings_form": FindingsForm(),
        "note_form": AnalysisNoteForm(initial={"analysis_note": submission.analysis_note}),
        "review_form": ReviewForm(),
        "score_choices": list(range(1, 11)),
    }
    context.update(overrides)
    return context


@login_required
def submission_detail_view(request, pk):
    blocked_response = require_apk_access_or_redirect(request)
    if blocked_response:
        return blocked_response

    submission = get_object_or_404(
        ApkSubmission.objects.select_related(
            "assigned_to", "source", "reviewed_by", "duplicate_of", "review_assigned_to"
        ),
        pk=pk,
    )
    profile = get_profile_for_user(request.user)
    if (
        user_is_chilonzor_worker(request.user)
        or user_is_chilonzor_team_admin(request.user)
    ) and not _can_open_chilonzor_review(request.user, profile, submission):
        return deny(request, translate("Bu ish Chilonzor xodimi sifatida sizga biriktirilmagan."))
    return render(request, "apk/submission_detail.html", _detail_context(request, submission))


def _workflow_action(request, pk, action, success_message, **kwargs):
    """Umumiy qobiq: workflow xatosini xabarga aylantirib, ish sahifasiga qaytaradi."""
    profile = get_profile_for_user(request.user)
    try:
        action(pk, profile, **kwargs)
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, success_message)
    return redirect("apk:submission_detail", pk=pk)


@login_required
@require_POST
def submission_claim_view(request, pk):
    blocked_response = require_worker_or_redirect(request)
    if blocked_response:
        return blocked_response
    if not user_is_kursant(request.user):
        messages.error(
            request,
            translate("Sizga jadvalda ustun ochilmagan - avval admin sizni kursant sifatida qo'shishi kerak."),
        )
        return redirect("apk:submission_detail", pk=pk)
    return _workflow_action(
        request, pk, workflow.claim, translate("Ish sizga biriktirildi - jadvalda sariq rangda.")
    )


@login_required
@require_POST
def submission_release_view(request, pk):
    blocked_response = require_worker_or_redirect(request)
    if blocked_response:
        return blocked_response
    response = _workflow_action(
        request,
        pk,
        workflow.release,
        translate("Ish qaytarib berildi - boshqa kursant olishi mumkin."),
        is_staff=request.user.is_staff,
    )
    return response


@login_required
@require_POST
def submission_send_view(request, pk):
    blocked_response = require_worker_or_redirect(request)
    if blocked_response:
        return blocked_response
    return _workflow_action(
        request,
        pk,
        workflow.send_to_chilonzor,
        translate("Chilonzorga yuborildi."),
        is_staff=request.user.is_staff,
    )


def _editable_submission_or_error(request, pk):
    """Topilma/izoh o'zgartirish uchun ish (yoki xato xabari bilan redirect)."""
    submission = get_object_or_404(ApkSubmission, pk=pk)
    profile = get_profile_for_user(request.user)
    if not submission.is_editable:
        return None, translate("Bu bosqichda ma'lumotni o'zgartirib bo'lmaydi.")
    if not request.user.is_staff and submission.assigned_to_id != profile.pk:
        return None, translate("Bu ish sizga biriktirilmagan.")
    return submission, None


@login_required
@require_POST
def finding_add_view(request, pk):
    blocked_response = require_worker_or_redirect(request)
    if blocked_response:
        return blocked_response

    submission, error = _editable_submission_or_error(request, pk)
    if error:
        messages.error(request, error)
        return redirect("apk:submission_detail", pk=pk)

    form = FindingsForm(request.POST)
    if form.is_valid():
        profile = get_profile_for_user(request.user)
        with transaction.atomic():
            added = sum(
                workflow.add_findings(submission, kind, values, profile)
                for kind, values in form.cleaned_data["parsed_values"].items()
                if values
            )
        if added:
            messages.success(request, translate("{count} ta qiymat qo'shildi.", count=added))
        else:
            messages.info(request, translate("Barcha qiymatlar allaqachon kiritilgan."))
        return redirect("apk:submission_detail", pk=pk)

    submission = get_object_or_404(
        ApkSubmission.objects.select_related("assigned_to", "source", "reviewed_by", "duplicate_of"),
        pk=pk,
    )
    return render(
        request,
        "apk/submission_detail.html",
        _detail_context(request, submission, findings_form=form),
    )


@login_required
@require_POST
def finding_delete_view(request, pk, finding_pk):
    blocked_response = require_worker_or_redirect(request)
    if blocked_response:
        return blocked_response

    submission, error = _editable_submission_or_error(request, pk)
    if error:
        messages.error(request, error)
        return redirect("apk:submission_detail", pk=pk)

    finding = get_object_or_404(ApkFinding, pk=finding_pk, submission=submission)
    with transaction.atomic():
        workflow.record_finding_deleted(submission, finding, get_profile_for_user(request.user))
        finding.delete()
    messages.success(request, translate("Qiymat o'chirildi."))
    return redirect("apk:submission_detail", pk=pk)


@login_required
@require_POST
def findings_copy_view(request, pk):
    """Shu APK yoki havola bo'yicha oldingi topilmalarni ko'chiradi."""
    blocked_response = require_worker_or_redirect(request)
    if blocked_response:
        return blocked_response

    submission, error = _editable_submission_or_error(request, pk)
    if error:
        messages.error(request, error)
        return redirect("apk:submission_detail", pk=pk)

    profile = get_profile_for_user(request.user)
    existing = set(submission.findings.values_list("kind", "value"))
    new_rows = []
    prior_findings = ApkFinding.objects.filter(
        submission__source_type=(ApkSubmission.SOURCE_LINK if submission.is_link else ApkSubmission.SOURCE_APK)
    )
    if submission.is_link:
        prior_findings = prior_findings.filter(submission__source_url=submission.source_url)
    else:
        prior_findings = prior_findings.filter(submission__sha256=submission.sha256)
    for finding in prior_findings.exclude(submission=submission).order_by("created_at", "pk"):
        key = (finding.kind, finding.value)
        if key in existing:
            continue
        existing.add(key)
        new_rows.append(
            ApkFinding(submission=submission, kind=finding.kind, value=finding.value, added_by=profile)
        )
    ApkFinding.objects.bulk_create(new_rows)

    if new_rows:
        messages.success(
            request, translate("{count} ta qiymat oldingi ishdan ko'chirildi.", count=len(new_rows))
        )
    else:
        messages.info(request, translate("Ko'chiriladigan yangi qiymat yo'q."))
    return redirect("apk:submission_detail", pk=pk)


@login_required
@require_POST
def analysis_note_view(request, pk):
    blocked_response = require_worker_or_redirect(request)
    if blocked_response:
        return blocked_response

    submission, error = _editable_submission_or_error(request, pk)
    if error:
        messages.error(request, error)
        return redirect("apk:submission_detail", pk=pk)

    form = AnalysisNoteForm(request.POST)
    if form.is_valid():
        submission.analysis_note = form.cleaned_data["analysis_note"].strip()
        with transaction.atomic():
            submission.save(update_fields=["analysis_note", "updated_at"])
            workflow.record_analysis_note(
                submission,
                get_profile_for_user(request.user),
                submission.analysis_note,
            )
        messages.success(request, translate("Izoh saqlandi."))
    return redirect("apk:submission_detail", pk=pk)


@login_required
def kursant_rating_view(request):
    """Kursantlar reytingi: tizimdagi har bir rol ko'radi."""
    from .rating import kursant_rating, tier_legend

    user = request.user
    if not (user.is_staff or user_has_apk_access(user) or user_is_osint_kursant(user)):
        return deny(request, translate("Reytingni ko'rishga ruxsatingiz yo'q."))
    rows = kursant_rating()
    return render(
        request,
        "apk/rating.html",
        {
            "rows": rows,
            "leaders": [row for row in rows[:3] if row["points"]],
            "legend": tier_legend(),
            "current_profile": get_profile_for_user(user),
        },
    )


@login_required
@require_POST
def submission_review_view(request, pk):
    """Chilonzor: qabul qiladi yoki kamchiliklarini yozib qaytaradi."""
    blocked_response = require_reviewer_or_redirect(request)
    if blocked_response:
        return blocked_response

    profile = get_profile_for_user(request.user)
    form = ReviewForm(request.POST)
    note = form.cleaned_data["note"].strip() if form.is_valid() else ""
    decision = request.POST.get("decision")

    try:
        if decision == "accept":
            try:
                score = int(request.POST.get("score") or 0)
            except ValueError:
                score = 0
            workflow.accept(pk, profile, note, is_staff=request.user.is_staff, score=score or None)
            messages.success(request, translate("Qabul qilindi. Kursantga {score} ball berildi.", score=score))
        elif decision == "return":
            workflow.send_back(pk, profile, note, is_staff=request.user.is_staff)
            messages.warning(request, translate("Kursantga qaytarildi."))
        else:
            messages.error(request, translate("Noto'g'ri amal."))
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("apk:submission_detail", pk=pk)


@login_required
@require_POST
def submission_assign_review_view(request, pk):
    if not user_can_assign_chilonzor_review(request.user):
        return deny(request, translate("Faqat Chilonzor admin ishni xodimga biriktira oladi."))

    reviewers = chilonzor_review_workers()
    actor_profile = get_profile_for_user(request.user)
    if user_is_chilonzor_team_admin(request.user) and not user_is_chilonzor_super_admin(request.user):
        reviewers = reviewers.filter(chilonzor_manager=actor_profile)
    form = ReviewAssignmentForm(request.POST, reviewers=reviewers)
    if not form.is_valid():
        messages.error(request, translate("Faol Chilonzor xodimini tanlang."))
        return redirect("apk:submission_detail", pk=pk)

    try:
        workflow.assign_review(
            pk,
            form.cleaned_data["reviewer"],
            actor_profile,
        )
        messages.success(request, translate("Ish Chilonzor xodimiga biriktirildi."))
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("apk:submission_detail", pk=pk)


@login_required
def submission_download_view(request, pk):
    blocked_response = require_apk_access_or_redirect(request)
    if blocked_response:
        return blocked_response

    submission = get_object_or_404(ApkSubmission, pk=pk)
    profile = get_profile_for_user(request.user)
    if (
        user_is_chilonzor_worker(request.user)
        or user_is_chilonzor_team_admin(request.user)
    ) and not _can_open_chilonzor_review(request.user, profile, submission):
        return deny(request, translate("Bu ish Chilonzor xodimi sifatida sizga biriktirilmagan."))
    try:
        handle = submission.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404(translate("Fayl topilmadi.")) from None

    response = FileResponse(
        handle,
        as_attachment=True,
        filename=submission.file_name,
        content_type="application/vnd.android.package-archive",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def submission_delete_view(request, pk):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    submission = get_object_or_404(ApkSubmission, pk=pk)
    submission.file.delete(save=False)
    submission.delete()
    messages.success(request, translate("Ish va APK fayl o'chirildi."))
    return redirect("apk:submission_list")


# --------------------------------------------------------------------------
# Chilonzor navbati
# --------------------------------------------------------------------------


@login_required
def review_queue_view(request):
    blocked_response = require_apk_access_or_redirect(request)
    if blocked_response:
        return blocked_response
    if not user_can_review(request.user):
        return deny(request, translate("Chilonzor ko'rib chiqish bo'limiga ruxsatingiz yo'q."))

    search = (request.GET.get("q") or "").strip()
    profile = get_profile_for_user(request.user)
    can_assign_review = user_can_assign_chilonzor_review(request.user)
    base = with_finding_counts(
        search_filter(
            ApkSubmission.objects.select_related(
                "assigned_to", "review_assigned_to", "review_assigned_to__account"
            ),
            search,
        )
    )
    if user_is_chilonzor_worker(request.user) and not request.user.is_staff:
        base = base.filter(review_assigned_to=profile)
    pending_queryset = base.filter(status=ApkSubmission.STATUS_SENT).order_by("sent_at", "pk")
    if user_is_chilonzor_team_admin(request.user) and not user_is_chilonzor_super_admin(request.user):
        pending_queryset = base.filter(status=ApkSubmission.STATUS_SENT).filter(
            Q(review_assigned_to__isnull=True)
            | Q(review_assigned_to__chilonzor_manager=profile)
        ).order_by("sent_at", "pk")
    paginator = Paginator(pending_queryset, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    now = timezone.now()
    pending = list(page.object_list)
    for item in pending:
        waited = now - (item.sent_at or item.created_at)
        item.wait_label = humanize_wait(waited)
        item.is_overdue = waited >= timedelta(hours=REVIEW_OVERDUE_HOURS)
    query = request.GET.copy()
    query.pop("page", None)
    decided_queryset = base.filter(
            status__in=[ApkSubmission.STATUS_ACCEPTED, ApkSubmission.STATUS_RETURNED],
            reviewed_at__isnull=False,
        ).select_related("reviewed_by").order_by("-reviewed_at")
    if user_is_chilonzor_worker(request.user) and not request.user.is_staff:
        decided_queryset = decided_queryset.filter(reviewed_by=profile)
    elif user_is_chilonzor_team_admin(request.user) and not user_is_chilonzor_super_admin(request.user):
        decided_queryset = decided_queryset.filter(reviewed_by__chilonzor_manager=profile)
    decided = list(decided_queryset[:50])
    # Sahifa tepasidagi ko'rsatkichlar (qidiruv hisobga olinadi).
    overdue_cutoff = now - timedelta(hours=REVIEW_OVERDUE_HOURS)
    overdue_count = pending_queryset.filter(
        Q(sent_at__lte=overdue_cutoff) | Q(sent_at__isnull=True, created_at__lte=overdue_cutoff)
    ).count()
    unassigned_count = pending_queryset.filter(review_assigned_to__isnull=True).count()
    decided_accepted = sum(1 for item in decided if item.status == ApkSubmission.STATUS_ACCEPTED)
    return render(
        request,
        "apk/review_queue.html",
        {
            "pending": pending,
            "page": page,
            "page_query": query.urlencode(),
            "overdue_hours": REVIEW_OVERDUE_HOURS,
            "overdue_count": overdue_count,
            "unassigned_count": unassigned_count,
            "decided": decided,
            "decided_accepted": decided_accepted,
            "decided_returned": len(decided) - decided_accepted,
            "search": search,
            "search_placeholder": translate("Fayl, yuboruvchi, IP, domen yoki Telegram ID..."),
            "is_filtered": bool(search),
            "result_count": paginator.count,
            "total_count": pending_queryset.count(),
            "filters": [],
            "can_review": not can_assign_review and user_can_review(request.user),
            "can_assign_review": can_assign_review,
        },
    )


def _decorate_employee_ratings(employees, since):
    employees = list(employees)
    if not employees:
        return employees, 0
    counts = {
        row["reviewed_by"]: row["count"]
        for row in ApkSubmission.objects.filter(
            reviewed_by__in=employees,
            status=ApkSubmission.STATUS_ACCEPTED,
            reviewed_at__gte=since,
        ).values("reviewed_by").annotate(count=Count("id"))
    }
    average = sum(counts.get(employee.pk, 0) for employee in employees) / len(employees)
    for employee in employees:
        employee.accepted_30d = counts.get(employee.pk, 0)
        if average and employee.accepted_30d > average * 1.2:
            employee.rating_class = "employee-rating--good"
            employee.row_rating_class = "employee-row--good"
            employee.rating_label = translate("O'rtachadan yuqori")
        elif average and employee.accepted_30d < average * 0.8:
            employee.rating_class = "employee-rating--low"
            employee.row_rating_class = "employee-row--low"
            employee.rating_label = translate("O'rtachadan past")
        else:
            employee.rating_class = "employee-rating--average"
            employee.row_rating_class = "employee-row--average"
            employee.rating_label = translate("O'rtacha")
    return employees, round(average, 1)


def _worker_group_for_admin(admin_group):
    return {
        GROUP_CHILONZOR_02_ADMIN: GROUP_CHILONZOR_OPER,
        GROUP_CHILONZOR_03_ADMIN: GROUP_CHILONZOR_HUB,
    }.get(admin_group)


def _assign_employee_team(employee, manager):
    admin_group = chilonzor_admin_group_for(manager.account)
    worker_group_name = _worker_group_for_admin(admin_group)
    if not worker_group_name:
        raise ValueError("Chilonzor xodimi uchun jamoa admini tanlanmagan.")

    previous_groups = Group.objects.filter(
        name__in=(GROUP_CHILONZOR, GROUP_CHILONZOR_OPER, GROUP_CHILONZOR_HUB)
    )
    employee.account.groups.remove(*previous_groups)
    worker_group, _created = Group.objects.get_or_create(name=worker_group_name)
    employee.account.groups.add(worker_group)
    employee.chilonzor_manager = manager
    employee.save(update_fields=["chilonzor_manager"])


@login_required
def chilonzor_team_view(request):
    if not (user_is_chilonzor_admin(request.user) or user_is_chilonzor_worker(request.user) or request.user.is_staff):
        return deny(request, translate("Chilonzor jamoasini ko'rishga ruxsatingiz yo'q."))

    if user_is_chilonzor_worker(request.user) and not request.user.is_staff:
        return redirect("apk:chilonzor_employee_history", pk=get_profile_for_user(request.user).pk)

    is_super_admin = user_is_chilonzor_super_admin(request.user)
    manager_group = chilonzor_admin_group_for(request.user)
    if not is_super_admin and not manager_group:
        return deny(request, translate("Chilonzor jamoasini ko'rishga ruxsatingiz yo'q."))

    manager_profile = get_profile_for_user(request.user)
    can_add_employee = bool(is_super_admin or manager_group)
    all_workers = chilonzor_review_workers()
    unassigned_workers = all_workers.filter(chilonzor_manager__isnull=True)
    team_managers = Users.objects.filter(
        account__is_active=True,
        account__groups__name__in=GROUP_CHILONZOR_ADMINS[1:],
    ).select_related("account").prefetch_related("account__groups").distinct()
    manager_choices = team_managers if is_super_admin else None
    create_form = ChilonzorEmployeeForm(team_managers=manager_choices)
    attach_form = AttachChilonzorEmployeeForm(
        employees=unassigned_workers,
        team_managers=manager_choices,
    )

    if request.method == "POST":
        if not can_add_employee:
            return deny(request, translate("Faqat jamoa admini xodim qo'sha oladi."))
        action = request.POST.get("action")
        if action == "create_employee":
            create_form = ChilonzorEmployeeForm(request.POST, team_managers=manager_choices)
            if create_form.is_valid():
                target_manager = (
                    create_form.cleaned_data["manager"] if is_super_admin else manager_profile
                )
                worker_group_name = _worker_group_for_admin(
                    chilonzor_admin_group_for(target_manager.account)
                )
                with transaction.atomic():
                    account = create_form.save(worker_group=worker_group_name)
                    employee, _created = Users.objects.get_or_create(
                        account=account,
                        defaults={"first_name": account.first_name, "last_name": account.last_name},
                    )
                    employee.chilonzor_manager = target_manager
                    employee.save(update_fields=["chilonzor_manager"])
                messages.success(request, translate("Xodim jamoaga qo'shildi."))
                return redirect("apk:chilonzor_team")
        elif action == "attach_employee":
            attach_form = AttachChilonzorEmployeeForm(
                request.POST,
                employees=unassigned_workers,
                team_managers=manager_choices,
            )
            if attach_form.is_valid():
                employee = attach_form.cleaned_data["employee"]
                target_manager = (
                    attach_form.cleaned_data["manager"] if is_super_admin else manager_profile
                )
                with transaction.atomic():
                    _assign_employee_team(employee, target_manager)
                messages.success(request, translate("Mavjud xodim jamoaga biriktirildi."))
                return redirect("apk:chilonzor_team")

    since = timezone.now() - timedelta(days=30)
    root_admin = Users.objects.filter(
        account__groups__name=GROUP_CHILONZOR_ADMINS[0],
        account__is_active=True,
    ).select_related("account").first()
    if root_admin is None and is_super_admin:
        root_admin = manager_profile

    if is_super_admin:
        workers, average = _decorate_employee_ratings(all_workers, since)
        manager_profiles = list(
            Users.objects.filter(
                account__groups__name__in=GROUP_CHILONZOR_ADMINS[1:],
            ).select_related("account").distinct()
        )
        teams = [
            {
                "manager": manager,
                "name": (
                    translate("Chilonzor Oper")
                    if chilonzor_admin_group_for(manager.account) == GROUP_CHILONZOR_02_ADMIN
                    else translate("Chilonzor Hub")
                ),
                "employees": [employee for employee in workers if employee.chilonzor_manager_id == manager.pk],
            }
            for manager in manager_profiles
        ]
        unassigned_employees = [employee for employee in workers if employee.chilonzor_manager_id is None]
    else:
        workers, average = _decorate_employee_ratings(
            all_workers.filter(chilonzor_manager=manager_profile),
            since,
        )
        teams = [
            {
                "manager": manager_profile,
                "name": (
                    translate("Chilonzor Oper")
                    if manager_group == GROUP_CHILONZOR_02_ADMIN
                    else translate("Chilonzor Hub")
                ),
                "employees": workers,
            }
        ]
        unassigned_employees = []

    return render(
        request,
        "apk/chilonzor_team.html",
        {
            "teams": teams,
            "root_admin": root_admin,
            "workers": workers,
            "unassigned_employees": unassigned_employees,
            "can_add_employee": can_add_employee,
            "create_employee_form": create_form,
            "attach_employee_form": attach_form,
            "has_unassigned_employees": unassigned_workers.exists() if can_add_employee else False,
            "can_choose_team": is_super_admin,
            "average_accepted_30d": average,
            "period_days": 30,
            "is_super_admin": is_super_admin,
        },
    )


@login_required
def chilonzor_employee_history_view(request, pk):
    requester = request.user
    if not (
        user_is_chilonzor_admin(requester)
        or user_is_chilonzor_worker(requester)
        or requester.is_staff
    ):
        return deny(request, translate("Xodimlar tarixini ko'rishga ruxsatingiz yo'q."))

    employee = get_object_or_404(
        Users.objects.select_related("account", "chilonzor_manager", "chilonzor_manager__account"),
        pk=pk,
    )
    if not employee.account or not user_is_chilonzor_worker(employee.account):
        return deny(request, translate("Bu foydalanuvchi Chilonzor xodimi emas."))

    current_profile = get_profile_for_user(requester)
    if user_is_chilonzor_super_admin(requester):
        pass
    elif user_is_chilonzor_team_admin(requester):
        if employee.chilonzor_manager_id != current_profile.pk:
            return deny(request, translate("Faqat o'z jamoangizdagi xodim tarixini ko'ra olasiz."))
    elif employee.pk != current_profile.pk:
        return deny(request, translate("Faqat o'z ishlaringiz tarixini ko'ra olasiz."))

    participation = (
        Q(review_assigned_to=employee)
        | Q(reviewed_by=employee)
        | Q(events__review_assignee=employee)
        | Q(events__actor=employee)
        | Q(findings__added_by=employee)
    )
    submissions = with_finding_counts(
        ApkSubmission.objects.filter(participation)
        .select_related("assigned_to", "review_assigned_to", "reviewed_by", "source")
        .distinct()
        .order_by("-updated_at", "-pk")
    )
    paginator = Paginator(submissions, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "apk/chilonzor_employee_history.html",
        {
            "employee": employee,
            "submissions": page.object_list,
            "page": page,
            "page_query": "",
            "result_count": paginator.count,
            "total_count": paginator.count,
        },
    )


@login_required
def _render_osint_task_page(request, *, create_form=None, result_form=None, result_task_id=None):
    can_submit = user_can_submit_osint_task(request.user)
    is_osint_kursant = user_is_osint_kursant(request.user)
    current_profile = get_profile_for_user(request.user)
    if can_submit and create_form is None:
        create_form = OsintTaskForm(row_prefix="new-task")

    task_queryset = (
        OsintTask.objects.select_related(
            "submitted_by",
            "submitted_by__account",
            "student",
            "student__account",
            "operator",
            "operator__account",
            "reviewed_by",
            "reviewed_by__account",
        )
        .prefetch_related("entries", "results")
    )
    if is_osint_kursant and not can_submit:
        task_queryset = task_queryset.filter(Q(student__isnull=True) | Q(student=current_profile))
    tasks = list(task_queryset.all())
    student_working_statuses = (
        OsintTask.STATUS_STUDENT_WORKING,
        OsintTask.STATUS_RETURNED,
    )
    for task in tasks:
        task.can_student_claim = (
            is_osint_kursant
            and task.status == OsintTask.STATUS_NEW
            and task.student_id is None
        )
        task.can_student_submit = (
            is_osint_kursant
            and task.student_id == current_profile.pk
            and task.status in student_working_statuses
        )
        task.can_operator_claim = (
            can_submit
            and task.status == OsintTask.STATUS_SENT
            and task.operator_id is None
        )
        task.can_operator_review = (
            can_submit
            and task.status == OsintTask.STATUS_OPERATOR_WORKING
            and task.operator_id == current_profile.pk
        )
        if task.can_student_submit:
            if result_form is not None and task.pk == result_task_id:
                task.result_form = result_form
            else:
                task.result_form = OsintTaskResultForm(
                    initial_pairs=[
                        {"telegram_id": row.telegram_id, "value": row.value}
                        for row in task.results.all()
                    ],
                    row_prefix=f"task-{task.pk}",
                )

    return render(
        request,
        "apk/osint_tasks.html",
        {
            "form": create_form,
            "tasks": tasks,
            "can_submit": can_submit,
            "is_osint_kursant": is_osint_kursant,
            "osint_profile": (
                Kursant.objects.filter(user=current_profile, kind=Kursant.TYPE_OSINT).first()
                if is_osint_kursant
                else None
            ),
        },
    )


@login_required
def osint_task_list_view(request):
    if not user_can_view_osint_tasks(request.user):
        return deny(request, translate("Bu Akademiya bo'limini ko'rishga ruxsatingiz yo'q."))

    can_submit = user_can_submit_osint_task(request.user)
    if request.method == "POST" and not can_submit:
        return deny(request, translate("Akademiyaga topshiriq yuborish uchun ruxsatingiz yo'q."))

    form = None
    if can_submit:
        form = OsintTaskForm(
            request.POST if request.method == "POST" else None,
            row_prefix="new-task",
        )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            task = OsintTask.objects.create(
                title=form.cleaned_data["title"],
                description=form.cleaned_data["description"],
                submitted_by=get_profile_for_user(request.user),
            )
            OsintTaskValue.objects.bulk_create(
                [
                    OsintTaskValue(task=task, order=index, **pair)
                    for index, pair in enumerate(form.cleaned_data["pairs"])
                ]
            )
        messages.success(request, translate("Topshiriq Akademiyaga yuborildi."))
        return redirect("apk:osint_tasks")

    return _render_osint_task_page(request, create_form=form)


@login_required
@require_POST
def osint_task_claim_view(request, pk):
    if not user_is_osint_kursant(request.user):
        return deny(request, translate("Faqat OSINT kursant topshiriq olishi mumkin."))
    get_object_or_404(OsintTask, pk=pk)
    profile = get_profile_for_user(request.user)
    try:
        osint_workflow.claim_by_student(pk, profile)
        messages.success(request, translate("Topshiriq sizga biriktirildi."))
    except osint_workflow.OsintWorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("apk:osint_tasks")


@login_required
@require_POST
def osint_task_submit_view(request, pk):
    if not user_is_osint_kursant(request.user):
        return deny(request, translate("Faqat OSINT kursant topshiriq yuborishi mumkin."))
    task = get_object_or_404(OsintTask, pk=pk, student__account=request.user)
    profile = get_profile_for_user(request.user)
    form = OsintTaskResultForm(request.POST, row_prefix=f"task-{task.pk}")
    if not form.is_valid():
        return _render_osint_task_page(
            request,
            result_form=form,
            result_task_id=task.pk,
        )
    try:
        osint_workflow.submit_by_student(pk, profile, form.cleaned_data["pairs"])
        messages.success(request, translate("Natijalar operatorlarga yuborildi."))
    except osint_workflow.OsintWorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("apk:osint_tasks")


@login_required
@require_POST
def osint_task_operator_claim_view(request, pk):
    if not user_can_submit_osint_task(request.user):
        return deny(request, translate("Faqat Chilonzor Oper topshiriqni ko'rib chiqishi mumkin."))
    get_object_or_404(OsintTask, pk=pk)
    profile = get_profile_for_user(request.user)
    try:
        osint_workflow.claim_by_operator(pk, profile)
        messages.success(request, translate("Topshiriq sizga biriktirildi."))
    except osint_workflow.OsintWorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("apk:osint_tasks")


@login_required
@require_POST
def osint_task_operator_review_view(request, pk):
    if not user_can_submit_osint_task(request.user):
        return deny(request, translate("Faqat Chilonzor Oper topshiriqni ko'rib chiqishi mumkin."))
    get_object_or_404(OsintTask, pk=pk)
    profile = get_profile_for_user(request.user)
    decision = request.POST.get("decision")
    try:
        if decision == "accept":
            osint_workflow.accept_by_operator(
                pk,
                profile,
                useful=request.POST.get("useful") == "on",
            )
            messages.success(request, translate("OSINT natijasi tasdiqlandi. Kursantga 10 ball berildi."))
        elif decision == "return":
            osint_workflow.return_to_student(pk, profile, request.POST.get("return_note", ""))
            messages.warning(request, translate("Topshiriq tuzatish uchun kursantga qaytarildi."))
        else:
            messages.error(request, translate("Noto'g'ri amal."))
    except osint_workflow.OsintWorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("apk:osint_tasks")


# --------------------------------------------------------------------------
# Role-based dashboards and Word reports
# --------------------------------------------------------------------------


def _dashboard_context(request):
    try:
        period_days = int(request.GET.get("period", 30))
    except (TypeError, ValueError):
        period_days = 30
    if period_days not in PERIOD_OPTIONS:
        period_days = 30
    return build_dashboard_context(request.user, period_days)


def _dashboard_access_or_redirect(request):
    blocked_response = require_apk_access_or_redirect(request)
    if blocked_response:
        return blocked_response
    if dashboard_role(request.user) is None:
        return require_admin_or_redirect(request)
    return None


@login_required
def dashboard_view(request):
    blocked_response = _dashboard_access_or_redirect(request)
    if blocked_response:
        return blocked_response
    return render(request, "apk/dashboard.html", _dashboard_context(request))


@login_required
def dashboard_report_view(request):
    blocked_response = _dashboard_access_or_redirect(request)
    if blocked_response:
        return blocked_response
    from .reports import build_word_report

    context = _dashboard_context(request)
    profile = getattr(request.user, "profile", None)
    context["prepared_by"] = (str(profile) if profile else "") or request.user.get_full_name() or request.user.username
    report = build_word_report(context)
    filename = f"raqamli-qalqon-{context['role']}-hisobot-{timezone.localdate():%Y%m%d}.docx"
    response = HttpResponse(
        report,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --------------------------------------------------------------------------
# Admin: kursantlar (jadval ustunlari)
# --------------------------------------------------------------------------


@login_required
def kursant_list_view(request):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    search = (request.GET.get("q") or "").strip()
    kursants = Kursant.objects.select_related("user", "user__account")
    if search:
        kursants = kursants.filter(
            Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__account__username__icontains=search)
            | Q(team__icontains=search)
        )
    kursants = list(
        kursants.annotate(
            work_count=Count("user__apk_assignments", distinct=True),
            accepted_count=Count(
                "user__apk_assignments",
                filter=Q(user__apk_assignments__status=ApkSubmission.STATUS_ACCEPTED),
                distinct=True,
            ),
        ).order_by("team", "sort_order", "user__first_name")
    )
    return render(
        request,
        "apk/kursant_list.html",
        {
            "kursants": kursants,
            "search": search,
            "search_placeholder": translate("Kursant ismi, login yoki guruh..."),
            "filters": [],
            "is_filtered": bool(search),
            "result_count": len(kursants),
            "total_count": Kursant.objects.count(),
        },
    )


@login_required
def kursant_create_view(request):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    form = KursantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, translate("Kursant jadvalga ustun sifatida qo'shildi."))
        return redirect("apk:kursant_list")
    return render(
        request,
        "apk/form_page.html",
        {
            "form": form,
            "page_title": translate("Jadvalga kursant qo'shish"),
            "submit_text": translate("Saqlash"),
            "back_url": reverse("apk:kursant_list"),
        },
    )


@login_required
def kursant_update_view(request, pk):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    kursant = get_object_or_404(Kursant, pk=pk)
    form = KursantForm(request.POST or None, instance=kursant)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, translate("Kursant ma'lumoti yangilandi."))
        return redirect("apk:kursant_list")
    return render(
        request,
        "apk/form_page.html",
        {
            "form": form,
            "page_title": translate("Kursantni tahrirlash"),
            "submit_text": translate("Yangilash"),
            "back_url": reverse("apk:kursant_list"),
        },
    )


@login_required
@require_POST
def kursant_delete_view(request, pk):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    get_object_or_404(Kursant, pk=pk).delete()
    messages.success(request, translate("Kursant jadvaldan olib tashlandi."))
    return redirect("apk:kursant_list")


# --------------------------------------------------------------------------
# Admin: API kalitlari
# --------------------------------------------------------------------------


@login_required
def api_client_list_view(request):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    form = ApiClientForm(request.POST or None)
    new_token = None
    new_client = None
    if request.method == "POST" and form.is_valid():
        new_client, new_token = form.save()
        form = ApiClientForm()

    return render(
        request,
        "apk/api_clients.html",
        {
            "clients": ApiClient.objects.select_related("user", "user__account"),
            "form": form,
            "new_token": new_token,
            "new_client": new_client,
            "api_url": request.build_absolute_uri(reverse("api_receive_apk")),
        },
    )


@login_required
@require_POST
def api_client_toggle_view(request, pk):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    client = get_object_or_404(ApiClient, pk=pk)
    client.is_active = not client.is_active
    client.save(update_fields=["is_active"])
    messages.success(
        request,
        translate("Kalit yoqildi.") if client.is_active else translate("Kalit o'chirildi (faolsiz)."),
    )
    return redirect("apk:api_clients")


@login_required
@require_POST
def api_client_delete_view(request, pk):
    blocked_response = require_admin_or_redirect(request)
    if blocked_response:
        return blocked_response

    get_object_or_404(ApiClient, pk=pk).delete()
    messages.success(request, translate("API kaliti o'chirildi."))
    return redirect("apk:api_clients")
