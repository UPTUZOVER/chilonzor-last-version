from django.db.models import Q

from .permissions import (
    get_role_label,
    user_can_assign_chilonzor_review,
    user_has_apk_access,
    user_is_apk_only,
    user_is_chilonzor,
    user_is_chilonzor_super_admin,
    user_is_chilonzor_team_admin,
    user_is_chilonzor_worker,
    user_is_kursant,
    user_can_view_osint_tasks,
)

EMPTY = {
    "show_apk_nav": False,
    "apk_role_label": "",
    "apk_only_user": False,
    "is_kursant_user": False,
    "is_chilonzor_user": False,
    "show_osint_nav": False,
    "apk_new_count": 0,
    "apk_returned_count": 0,
    "apk_review_count": 0,
}


def apk_nav(request):
    """Menyudagi "APK tahlil" bo'limi va nishonlar (kutayotgan ishlar soni)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return dict(EMPTY)

    has_access = user_has_apk_access(user)
    context = dict(EMPTY)
    context.update(
        {
            "show_apk_nav": has_access,
            "apk_role_label": get_role_label(user),
            "apk_only_user": user_is_apk_only(user),
        }
    )
    context["show_osint_nav"] = user_can_view_osint_tasks(user)
    if not has_access:
        return context

    from .models import ApkSubmission

    is_kursant = user_is_kursant(user)
    is_chilonzor = user_is_chilonzor(user)
    context["is_kursant_user"] = is_kursant
    context["is_chilonzor_user"] = is_chilonzor

    if is_kursant:
        profile = getattr(user, "profile", None)
        context["apk_new_count"] = ApkSubmission.objects.filter(
            status=ApkSubmission.STATUS_NEW
        ).count()
        if profile is not None:
            context["apk_returned_count"] = ApkSubmission.objects.filter(
                status=ApkSubmission.STATUS_RETURNED, assigned_to=profile
            ).count()
    if is_chilonzor or user.is_staff:
        review_count = ApkSubmission.objects.filter(status=ApkSubmission.STATUS_SENT)
        if user_is_chilonzor_worker(user) and not user_can_assign_chilonzor_review(user):
            profile = getattr(user, "profile", None)
            review_count = review_count.filter(review_assigned_to=profile) if profile else review_count.none()
        elif user_is_chilonzor_team_admin(user) and not user_is_chilonzor_super_admin(user):
            profile = getattr(user, "profile", None)
            review_count = (
                review_count.filter(
                    Q(review_assigned_to__isnull=True)
                    | Q(review_assigned_to__chilonzor_manager=profile)
                )
                if profile
                else review_count.none()
            )
        context["apk_review_count"] = review_count.count()
    return context
