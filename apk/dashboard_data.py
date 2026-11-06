"""Role-aware analytics for the APK dashboards."""

from datetime import timedelta
from math import pi

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from app.ui_i18n import translate

from .models import ApkEvent, ApkFinding, ApkSubmission, Kursant
from .permissions import (
    user_is_chilonzor_super_admin,
    user_is_chilonzor_team_admin,
    user_is_chilonzor,
    user_is_chilonzor_worker,
    user_is_kursant,
    user_is_mvd,
)


PERIOD_OPTIONS = (7, 30, 90)
REVIEW_OVERDUE_HOURS = 48

CHART_COLORS = {
    ApkSubmission.STATUS_NEW: "#64748b",
    ApkSubmission.STATUS_IN_PROGRESS: "#4f46e5",
    ApkSubmission.STATUS_SENT: "#f59e0b",
    ApkSubmission.STATUS_RETURNED: "#ef4444",
    ApkSubmission.STATUS_ACCEPTED: "#10b981",
}
FINDING_COLORS = {
    ApkFinding.KIND_IP: "#4f46e5",
    ApkFinding.KIND_DOMAIN: "#0891b2",
    ApkFinding.KIND_TELEGRAM: "#f59e0b",
}


def dashboard_role(user):
    if user.is_staff:
        return "admin"
    if user_is_chilonzor(user):
        return "chilonzor"
    if user_is_mvd(user):
        return "mvd"
    if user_is_kursant(user):
        return "kursant"
    return None


def _chart_rows(rows):
    """Attach percentages and SVG donut stroke geometry to chart rows."""
    total = sum(row["count"] for row in rows)
    circumference = 2 * pi * 40
    offset = 0.0
    result = []
    for row in rows:
        share = row["count"] * 100 / total if total else 0
        length = circumference * share / 100
        item = {
            **row,
            "share": round(share),
            "dasharray": f"{length:.2f} {max(circumference - length, 0):.2f}",
            "dashoffset": f"-{offset:.2f}",
        }
        result.append(item)
        offset += length
    return result, total


def _status_rows(counts):
    return [
        {
            "label": str(label),
            "status": code,
            "color": CHART_COLORS[code],
            "count": counts.get(code, 0),
        }
        for code, label in ApkSubmission.STATUS_CHOICES
    ]


def _finding_rows(submissions):
    counts = {
        row["kind"]: row["count"]
        for row in ApkFinding.objects.filter(submission__in=submissions)
        .values("kind")
        .annotate(count=Count("id"))
    }
    return [
        {
            "label": str(label),
            "kind": kind,
            "color": FINDING_COLORS[kind],
            "count": counts.get(kind, 0),
        }
        for kind, label in ApkFinding.KIND_CHOICES
    ]


def _repeated_findings(submissions):
    groups = {kind: [] for kind, _label in ApkFinding.KIND_CHOICES}
    values = (
        ApkFinding.objects.filter(submission__in=submissions)
        .values("kind", "value")
        .annotate(count=Count("submission", distinct=True))
        .filter(count__gte=2)
        .order_by("kind", "-count", "value")
    )
    for row in values:
        if len(groups[row["kind"]]) < 5:
            groups[row["kind"]].append(row)
    return [
        {"label": str(label), "items": groups[kind]}
        for kind, label in ApkFinding.KIND_CHOICES
    ]


def _trend_rows(submissions, role, start, end, period_days):
    if role == "chilonzor":
        field = "reviewed_at"
        title = translate("Kunlik qarorlar soni")
        tracked = submissions.filter(
            status__in=(ApkSubmission.STATUS_ACCEPTED, ApkSubmission.STATUS_RETURNED)
        )
    elif role == "kursant":
        field = "sent_at"
        title = translate("Kunlik yuborilgan tahlillar")
        tracked = submissions.filter(sent_at__isnull=False)
    else:
        field = "created_at"
        title = translate("Kunlik kelgan APK soni")
        tracked = submissions

    grouped = {
        row["day"]: row["count"]
        for row in tracked.filter(
            **{f"{field}__date__gte": start, f"{field}__date__lte": end}
        )
        .annotate(day=TruncDate(field))
        .values("day")
        .annotate(count=Count("id"))
    }
    days = [start + timedelta(days=offset) for offset in range(period_days)]
    maximum = max([grouped.get(day, 0) for day in days] + [1])
    return [
        {
            "day": day,
            "count": grouped.get(day, 0),
            "height": round(grouped.get(day, 0) * 100 / maximum),
        }
        for day in days
    ], title


def _display_name(first_name, last_name, username=""):
    name = f"{first_name or ''} {last_name or ''}".strip()
    return name or username or translate("Noma'lum manba")


def _time_waiting(started_at, now):
    if not started_at:
        return "—"
    seconds = max(int((now - started_at).total_seconds()), 0)
    if seconds >= 86400:
        return translate("{count} kun", count=seconds // 86400)
    if seconds >= 3600:
        return translate("{count} soat", count=seconds // 3600)
    return translate("{count} daqiqa", count=max(seconds // 60, 1))


def build_dashboard_context(user, period_days=30):
    role = dashboard_role(user)
    if role is None:
        return None

    period_days = period_days if period_days in PERIOD_OPTIONS else 30
    today = timezone.localdate()
    period_start = today - timedelta(days=period_days - 1)
    period_end = today
    now = timezone.now()

    submissions = ApkSubmission.objects.all()
    profile = getattr(user, "profile", None)
    if role == "kursant":
        submissions = submissions.filter(assigned_to=profile) if profile else submissions.none()
    elif role == "chilonzor" and user_is_chilonzor_worker(user):
        submissions = (
            submissions.filter(review_assigned_to=profile) if profile else submissions.none()
        )
    elif role == "chilonzor" and user_is_chilonzor_team_admin(user) and not user_is_chilonzor_super_admin(user):
        submissions = submissions.filter(
            Q(status=ApkSubmission.STATUS_SENT, review_assigned_to__isnull=True)
            | Q(review_assigned_to__chilonzor_manager=profile)
            | Q(reviewed_by__chilonzor_manager=profile)
        ) if profile else submissions.none()

    status_counts = {
        row["status"]: row["count"]
        for row in submissions.values("status").annotate(count=Count("id"))
    }
    total = sum(status_counts.values())
    statuses = _status_rows(status_counts)
    findings = _finding_rows(submissions)
    repeated_groups = _repeated_findings(submissions)
    source_rows = []
    performance_rows = []

    if role == "chilonzor":
        decision_queryset = submissions.filter(
            status__in=(ApkSubmission.STATUS_ACCEPTED, ApkSubmission.STATUS_RETURNED),
            reviewed_at__date__gte=period_start,
            reviewed_at__date__lte=period_end,
        )
        decision_counts = {
            row["status"]: row["count"]
            for row in decision_queryset.values("status").annotate(count=Count("id"))
        }
        chart_source = [
            {
                "label": str(label),
                "color": CHART_COLORS[code],
                "count": decision_counts.get(code, 0),
            }
            for code, label in ApkSubmission.STATUS_CHOICES
            if code in (ApkSubmission.STATUS_ACCEPTED, ApkSubmission.STATUS_RETURNED)
        ]
        decision_total = sum(decision_counts.values())
        queue = submissions.filter(status=ApkSubmission.STATUS_SENT)
        overdue_count = queue.filter(sent_at__lt=now - timedelta(hours=REVIEW_OVERDUE_HOURS)).count()
        decided = list(
            decision_queryset.filter(sent_at__isnull=False, reviewed_at__isnull=False).values_list(
                "sent_at", "reviewed_at"
            )
        )
        durations = [max(0, (reviewed - sent).total_seconds() / 3600) for sent, reviewed in decided]
        average_hours = round(sum(durations) / len(durations), 1) if durations else None
        acceptance_rate = round(
            decision_counts.get(ApkSubmission.STATUS_ACCEPTED, 0) * 100 / decision_total
        ) if decision_total else 0
        kpis = [
            {"label": translate("Ko'rib chiqish navbatida"), "value": queue.count(), "hint": translate("qaror kutilmoqda"), "tone": "amber"},
            {"label": translate("Kechikkan ishlar"), "value": overdue_count, "hint": translate("48 soatdan ko'p kutilgan"), "tone": "red"},
            {"label": translate("Davrda qarorlar"), "value": decision_total, "hint": translate("qabul qilingan yoki qaytarilgan"), "tone": "blue"},
            {"label": translate("Qabul qilish darajasi"), "value": f"{acceptance_rate}%", "hint": translate("tanlangan davr bo'yicha"), "tone": "green"},
            {"label": translate("O'rtacha ko'rib chiqish"), "value": f"{average_hours} soat" if average_hours is not None else "—", "hint": translate("yuborilgandan qarorgacha"), "tone": "blue"},
        ]
        chart_rows, chart_total = _chart_rows(chart_source)
        extra_rows = list(
            queue.select_related("assigned_to")
            .order_by("sent_at", "created_at")[:8]
        )
        waiting_rows = [
            {"submission": item, "waiting": _time_waiting(item.sent_at, now), "overdue": bool(item.sent_at and item.sent_at < now - timedelta(hours=REVIEW_OVERDUE_HOURS))}
            for item in extra_rows
        ]
        event_query = ApkEvent.objects.filter(
            submission__in=submissions,
            action__in=(ApkEvent.ACTION_ACCEPTED, ApkEvent.ACTION_RETURNED),
        )
        recent_events = list(event_query.select_related("actor", "submission").order_by("-created_at", "-id")[:10])
        extra_title = translate("Ko'rib chiqish navbati")
        trend_submissions = submissions

    elif role == "kursant":
        active_count = status_counts.get(ApkSubmission.STATUS_IN_PROGRESS, 0) + status_counts.get(ApkSubmission.STATUS_RETURNED, 0)
        waiting_review_count = status_counts.get(ApkSubmission.STATUS_SENT, 0)
        available_count = ApkSubmission.objects.filter(status=ApkSubmission.STATUS_NEW, assigned_to__isnull=True).count()
        kpis = [
            {"label": translate("Menga biriktirilgan"), "value": total, "hint": translate("barcha ishlar"), "tone": "blue"},
            {"label": translate("Tahlil va tuzatish"), "value": active_count, "hint": translate("davom ettirish kerak"), "tone": "amber"},
            {"label": translate("Ko'rib chiqilmoqda"), "value": waiting_review_count, "hint": translate("Chilonzordan javob kutilmoqda"), "tone": "blue"},
            {"label": translate("Qabul qilingan"), "value": status_counts.get(ApkSubmission.STATUS_ACCEPTED, 0), "hint": translate("yakunlangan tahlillar"), "tone": "green"},
            {"label": translate("Yangi ishlar"), "value": available_count, "hint": translate("olish mumkin"), "tone": "blue"},
        ]
        chart_rows, chart_total = _chart_rows(statuses)
        waiting_rows = []
        extra_rows = list(submissions.filter(status=ApkSubmission.STATUS_RETURNED).order_by("-updated_at")[:8])
        recent_events = list(
            ApkEvent.objects.filter(submission__in=submissions)
            .select_related("actor", "submission")
            .order_by("-created_at", "-id")[:10]
        )
        extra_title = translate("Tuzatish uchun qaytarilgan ishlar")
        trend_submissions = submissions

    elif role == "mvd":
        recent_count = submissions.filter(created_at__date__gte=period_start, created_at__date__lte=period_end).count()
        duplicate_count = submissions.filter(
            source_type=ApkSubmission.SOURCE_APK, duplicate_of__isnull=False
        ).count()
        kpis = [
            {"label": translate("Jami kelgan APK"), "value": total, "hint": translate("barcha manbalardan"), "tone": "blue"},
            {"label": translate("Davrda kelgan"), "value": recent_count, "hint": translate("tanlangan sana oralig'ida"), "tone": "blue"},
            {"label": translate("Yangi navbatda"), "value": status_counts.get(ApkSubmission.STATUS_NEW, 0), "hint": translate("kursant olishini kutmoqda"), "tone": "amber"},
            {"label": translate("Takroriy fayllar"), "value": duplicate_count, "hint": translate("SHA-256 mos kelgan"), "tone": "violet"},
            {"label": translate("Havolalar"), "value": submissions.filter(source_type=ApkSubmission.SOURCE_LINK).count(), "hint": translate("qabul qilingan havolalar"), "tone": "green"},
        ]
        chart_rows, chart_total = _chart_rows(statuses)
        source_rows = [
            {
                "name": _display_name(row["source__first_name"], row["source__last_name"], row["source__account__username"]),
                "count": row["count"],
            }
            for row in submissions.values("source__first_name", "source__last_name", "source__account__username")
            .annotate(count=Count("id"))
            .order_by("-count", "source__first_name")[:8]
        ]
        waiting_rows = []
        extra_rows = []
        recent_events = list(ApkEvent.objects.select_related("actor", "submission").order_by("-created_at", "-id")[:10])
        extra_title = translate("APK yuborgan manbalar")
        trend_submissions = submissions

    else:  # Admin
        recent_count = submissions.filter(created_at__date__gte=period_start, created_at__date__lte=period_end).count()
        kpis = [
            {"label": translate("Jami APK"), "value": total, "hint": translate("barcha holatlar"), "tone": "blue"},
            {"label": translate("Davrda kelgan"), "value": recent_count, "hint": translate("tanlangan sana oralig'ida"), "tone": "blue"},
            {"label": translate("Yangi navbatda"), "value": status_counts.get(ApkSubmission.STATUS_NEW, 0), "hint": translate("kursant olishini kutmoqda"), "tone": "amber"},
            {"label": translate("Tahlilda"), "value": status_counts.get(ApkSubmission.STATUS_IN_PROGRESS, 0), "hint": translate("kursantlar ishlamoqda"), "tone": "violet"},
            {"label": translate("Chilonzor navbatida"), "value": status_counts.get(ApkSubmission.STATUS_SENT, 0), "hint": translate("qaror kutilmoqda"), "tone": "amber"},
            {"label": translate("Havolalar"), "value": submissions.filter(source_type=ApkSubmission.SOURCE_LINK).count(), "hint": translate("qabul qilingan havolalar"), "tone": "green"},
        ]
        chart_rows, chart_total = _chart_rows(statuses)
        active_statuses = (ApkSubmission.STATUS_IN_PROGRESS, ApkSubmission.STATUS_RETURNED, ApkSubmission.STATUS_SENT)
        kursants = Kursant.objects.select_related("user").filter(
            is_active=True,
            kind=Kursant.TYPE_APK,
        ).annotate(
            active_count=Count("user__apk_assignments", filter=Q(user__apk_assignments__status__in=active_statuses), distinct=True),
            accepted_count=Count("user__apk_assignments", filter=Q(user__apk_assignments__status=ApkSubmission.STATUS_ACCEPTED), distinct=True),
            returned_count=Count("user__apk_assignments", filter=Q(user__apk_assignments__status=ApkSubmission.STATUS_RETURNED), distinct=True),
        ).order_by("-accepted_count", "user__first_name")
        performance_rows = [
            {"name": str(item.user), "active": item.active_count, "accepted": item.accepted_count, "returned": item.returned_count}
            for item in kursants[:12]
        ]
        waiting_rows = []
        extra_rows = []
        recent_events = list(ApkEvent.objects.select_related("actor", "submission").order_by("-created_at", "-id")[:10])
        extra_title = translate("Kursantlar faoliyati")
        trend_submissions = submissions

    daily, trend_title = _trend_rows(trend_submissions, role, period_start, period_end, period_days)
    finding_chart, finding_chart_total = _chart_rows(findings)
    return {
        "role": role,
        "role_title": {
            "admin": translate("Admin dashboardi"),
            "mvd": translate("MVD dashboardi"),
            "chilonzor": translate("Chilonzor dashboardi"),
            "kursant": translate("Kursant dashboardi"),
        }[role],
        "role_description": {
            "admin": translate("Tizimning umumiy ko'rsatkichlari va ish jarayonini kuzating."),
            "mvd": translate("Kelgan APKlar, manbalar va tahlil natijalarini kuzating."),
            "chilonzor": translate("Ko'rib chiqish navbati va qarorlar samaradorligini kuzating."),
            "kursant": translate("O'zingizga biriktirilgan ishlar va tahlil natijalarini kuzating."),
        }[role],
        "period_days": period_days,
        "period_start": period_start,
        "period_end": period_end,
        "period_options": [{"days": days, "selected": days == period_days} for days in PERIOD_OPTIONS],
        "kpis": kpis,
        "status_rows": statuses,
        "chart_rows": chart_rows,
        "chart_total": chart_total,
        "daily": daily,
        "trend_title": trend_title,
        "trend_max": max((item["count"] for item in daily), default=0),
        "finding_rows": findings,
        "finding_chart": finding_chart,
        "finding_chart_total": finding_chart_total,
        "repeated_groups": repeated_groups,
        "has_repeated": any(group["items"] for group in repeated_groups),
        "source_rows": source_rows,
        "performance_rows": performance_rows,
        "waiting_rows": waiting_rows,
        "extra_rows": extra_rows,
        "extra_title": extra_title,
        "recent_events": recent_events,
    }
