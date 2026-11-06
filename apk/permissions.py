"""APK bo'limi uchun rol asosidagi ruxsatlar.

Rollar:
  - Admin (is_staff)  - hamma narsa.
  - APK kursant       - APK ishlarini oladi, tahlil qiladi va Chilonzorga yuboradi.
  - OSINT kursant     - APK bo'limiga kira olmaydi.
  - MVD               - hammasini ko'rib turadi (faqat o'qish). API orqali ma'lumot
                        yuboruvchi hisoblar ham MVD.
  - Chilonzor         - kursant yuborgan tahlilni qabul qiladi yoki kamchiliklarini
                        yozib qaytaradi.
  - Chilonzor Oper    - APK ko'rib chiqish huquqi va Akademiyaga topshiriq yuborish.
  - Chilonzor Hub     - Chilonzor ko'rib chiqish xodimlari.
"""

from django.contrib import messages
from django.shortcuts import redirect

from app.ui_i18n import translate
from app.views import account_has_group

GROUP_MVD = "MVD"
GROUP_CHILONZOR = "Chilonzor"
GROUP_CHILONZOR_OPER = "chilonzor_oper"
GROUP_CHILONZOR_HUB = "chilonzor_hub"
GROUP_CHILONZOR_01_ADMIN = "Chilonzor admin 01"
GROUP_CHILONZOR_02_ADMIN = "Chilonzor admin 02"
GROUP_CHILONZOR_03_ADMIN = "Chilonzor admin 03"
GROUP_CHILONZOR_ADMINS = (
    GROUP_CHILONZOR_01_ADMIN,
    GROUP_CHILONZOR_02_ADMIN,
    GROUP_CHILONZOR_03_ADMIN,
)

ROLE_GROUPS = (
    GROUP_MVD,
    GROUP_CHILONZOR,
    GROUP_CHILONZOR_OPER,
    GROUP_CHILONZOR_HUB,
    *GROUP_CHILONZOR_ADMINS,
)

ROLE_GROUP_LABELS = {
    GROUP_MVD: "MVD",
    GROUP_CHILONZOR: "Chilonzor",
    GROUP_CHILONZOR_OPER: "Chilonzor Oper",
    GROUP_CHILONZOR_HUB: "Chilonzor Hub",
    GROUP_CHILONZOR_01_ADMIN: "Chilonzor admin 01",
    GROUP_CHILONZOR_02_ADMIN: "Chilonzor admin 02",
    GROUP_CHILONZOR_03_ADMIN: "Chilonzor admin 03",
}


def _is_authenticated(user):
    return bool(getattr(user, "is_authenticated", False))


def user_is_in_any_group(user, *group_names):
    if not _is_authenticated(user):
        return False
    return any(account_has_group(user, group_name) for group_name in group_names)


def user_is_kursant(user):
    """APK ishlarini ko'rishi va bajarishi mumkin bo'lgan kursant."""
    if not _is_authenticated(user):
        return False
    from .models import Kursant

    return Kursant.objects.filter(
        user__account=user,
        is_active=True,
        kind=Kursant.TYPE_APK,
    ).exists()


def user_is_osint_kursant(user):
    if not _is_authenticated(user):
        return False
    from .models import Kursant

    return Kursant.objects.filter(
        user__account=user,
        is_active=True,
        kind=Kursant.TYPE_OSINT,
    ).exists()


def user_is_mvd(user):
    return user_is_in_any_group(user, GROUP_MVD)


def user_is_chilonzor(user):
    return user_is_in_any_group(
        user,
        GROUP_CHILONZOR,
        GROUP_CHILONZOR_OPER,
        GROUP_CHILONZOR_HUB,
        *GROUP_CHILONZOR_ADMINS,
    )


def user_is_chilonzor_oper(user):
    return user_is_in_any_group(user, GROUP_CHILONZOR_OPER)


def user_is_chilonzor_admin(user):
    return user_is_in_any_group(user, *GROUP_CHILONZOR_ADMINS)


def user_is_chilonzor_super_admin(user):
    return _is_authenticated(user) and (
        user.is_staff or user_is_in_any_group(user, GROUP_CHILONZOR_01_ADMIN)
    )


def user_is_chilonzor_team_admin(user):
    return user_is_in_any_group(user, GROUP_CHILONZOR_02_ADMIN, GROUP_CHILONZOR_03_ADMIN)


def chilonzor_admin_group_for(user):
    if user_is_in_any_group(user, GROUP_CHILONZOR_02_ADMIN):
        return GROUP_CHILONZOR_02_ADMIN
    if user_is_in_any_group(user, GROUP_CHILONZOR_03_ADMIN):
        return GROUP_CHILONZOR_03_ADMIN
    return None


def user_is_chilonzor_worker(user):
    """Xodimlar vazifani faqat admin biriktirgandan keyin ko'rib chiqadi."""
    return user_is_chilonzor(user) and not user_is_chilonzor_admin(user)


def user_can_assign_chilonzor_review(user):
    return _is_authenticated(user) and (
        user.is_staff or user_is_chilonzor_admin(user)
    )


def user_has_apk_access(user):
    if not _is_authenticated(user):
        return False
    if user.is_staff:
        return True
    if user_is_osint_kursant(user):
        return False
    if user_is_in_any_group(user, *ROLE_GROUPS):
        return True
    return user_is_kursant(user)


def user_can_work(user):
    """APK ustida ishlash (olish, topilma kiritish, yuborish): kursant yoki admin."""
    return _is_authenticated(user) and (user.is_staff or user_is_kursant(user))


def user_can_review(user):
    """Qabul qilish yoki qaytarish: Chilonzor yoki admin."""
    return _is_authenticated(user) and (user.is_staff or user_is_chilonzor(user))


def user_can_submit_osint_task(user):
    return _is_authenticated(user) and (user.is_staff or user_is_chilonzor_oper(user))


def user_can_view_osint_tasks(user):
    return _is_authenticated(user) and (
        user.is_staff or user_is_chilonzor_oper(user) or user_is_osint_kursant(user)
    )


def user_is_apk_only(user):
    """Faqat APK bo'limiga kirishi kerak bo'lgan foydalanuvchi.

    MVD / Chilonzor / Chilonzor Oper xodimlari uchun loyihaning qolgan bo'limlari
    (Foydalanuvchilar, Guruhlar) yopiq. Admin (is_staff) bundan mustasno."""
    if not _is_authenticated(user):
        return False
    if user.is_staff:
        return False
    return user_is_in_any_group(user, *ROLE_GROUPS)


def get_role_label(user):
    if not _is_authenticated(user):
        return ""
    labels = []
    if user.is_staff:
        labels.append(translate("Admin"))
    for group_name in ROLE_GROUPS:
        if group_name == GROUP_CHILONZOR and user_is_chilonzor_admin(user):
            continue
        if account_has_group(user, group_name):
            labels.append(translate(ROLE_GROUP_LABELS[group_name]))
    if user_is_kursant(user):
        labels.append(translate("APK kursant"))
    elif user_is_osint_kursant(user):
        labels.append(translate("OSINT kursant"))
    return " / ".join(labels)


def deny(request, message):
    """Ruxsat yo'q - xabar chiqarib, foydalanuvchining o'z sahifasiga qaytaradi.

    APK bo'limiga umuman ruxsati borlar jadvalga, qolganlari "ruxsat yo'q"
    sahifasiga yuboriladi. `apk:home` ruxsati borni hech qachon rad etmaydi,
    shuning uchun cheksiz redirect hosil bo'lmaydi."""
    messages.error(request, message)
    if user_has_apk_access(request.user):
        return redirect("apk:home")
    return redirect("app:home")


def require_apk_access_or_redirect(request):
    if user_has_apk_access(request.user):
        return None
    return deny(request, translate("Bu bo'lim uchun sizda ruxsat yo'q."))


def require_worker_or_redirect(request):
    if user_can_work(request.user):
        return None
    return deny(request, translate("Faqat kursant yoki admin bu amalni bajara oladi."))


def require_reviewer_or_redirect(request):
    if user_can_review(request.user):
        return None
    return deny(request, translate("Faqat Chilonzor, Chilonzor Oper yoki admin bu amalni bajara oladi."))


def require_admin_or_redirect(request):
    if request.user.is_staff:
        return None
    return deny(request, translate("Bu bo'lim faqat admin uchun."))
