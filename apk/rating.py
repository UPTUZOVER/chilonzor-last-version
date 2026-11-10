"""Kursantlar reytingi.

Chilonzor xodimi APK tahlilini qabul qilganda 1-10 ball qo'yadi (ApkSubmission.score).
  - Jami ball   - qabul qilingan ishlar ballari yig'indisi; reyting shu bo'yicha tartiblanadi.
  - Sifat (0-10) - o'rtacha ball x qabul qilinish ulushi (qabul / (qabul + qaytarishlar)).
    Sifat besh darajaga bo'linadi: to'q qizil, och qizil, oq, och yashil, to'q yashil.
"""

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from app.ui_i18n import translate

from .models import ApkSubmission, Kursant

SCORE_CHOICES = list(range(1, 11))

# (pastki chegara, CSS darajasi, nom) - sifat ko'rsatkichi bo'yicha, yuqoridan pastga.
TIERS = (
    (8.5, "t5", "A'lo"),
    (7.0, "t4", "Yaxshi"),
    (5.0, "t3", "O'rtacha"),
    (3.0, "t2", "Past"),
    (0.0, "t1", "Juda past"),
)


def tier_for(quality):
    if quality is None:
        return {"key": "t0", "label": translate("Baho yo'q")}
    for threshold, key, label in TIERS:
        if quality >= threshold:
            return {"key": key, "label": translate(label)}
    return {"key": "t1", "label": translate("Juda past")}


def tier_legend():
    return [
        {"key": key, "label": translate(label), "range": f"{threshold:g}+" if threshold else f"< {TIERS[-2][0]:g}"}
        for threshold, key, label in TIERS
    ]


def kursant_rating():
    """Faol APK kursantlar: o'rin, jami ball, qabul/qaytarish, o'rtacha ball, sifat va daraja."""
    kursants = list(
        Kursant.objects.filter(is_active=True, kind=Kursant.TYPE_APK).select_related("user", "user__account")
    )
    stats = {
        row["assigned_to"]: row
        for row in ApkSubmission.objects.filter(assigned_to__in=[k.user_id for k in kursants])
        .values("assigned_to")
        .annotate(
            accepted=Count("id", filter=Q(status=ApkSubmission.STATUS_ACCEPTED)),
            scored=Count("id", filter=Q(status=ApkSubmission.STATUS_ACCEPTED, score__isnull=False)),
            points=Coalesce(Sum("score", filter=Q(status=ApkSubmission.STATUS_ACCEPTED)), 0),
            returns=Coalesce(Sum("return_count"), 0),
            active=Count(
                "id",
                filter=Q(status__in=(
                    ApkSubmission.STATUS_IN_PROGRESS, ApkSubmission.STATUS_SENT, ApkSubmission.STATUS_RETURNED,
                )),
            ),
        )
    }
    rows = []
    for kursant in kursants:
        row = stats.get(kursant.user_id, {})
        accepted, scored = row.get("accepted", 0), row.get("scored", 0)
        points, returns = row.get("points", 0), row.get("returns", 0)
        average = round(points / scored, 1) if scored else None
        decisions = accepted + returns
        acceptance = round(accepted * 100 / decisions) if decisions else None
        quality = round(average * accepted / decisions, 1) if average is not None and decisions else None
        rows.append({
            "profile": kursant.user,
            "team": kursant.team,
            "points": points,
            "accepted": accepted,
            "returns": returns,
            "active": row.get("active", 0),
            "average": average,
            "acceptance": acceptance,
            "quality": quality,
            "quality_width": round(quality * 10) if quality is not None else 0,
            "tier": tier_for(quality),
        })
    rows.sort(key=lambda item: (-item["points"], -(item["quality"] or -1), -item["accepted"], str(item["profile"])))
    for position, item in enumerate(rows, start=1):
        item["position"] = position
    return rows
