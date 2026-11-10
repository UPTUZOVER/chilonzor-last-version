from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Group
from django.db.models import Q

from app.forms import BaseStyledForm, BaseStyledPlainForm
from app.models import Users
from app.ui_i18n import lazy_translate as _, translate

from .models import ApiClient, ApkFinding, Kursant
from .parsing import parse_lines
from .permissions import (
    GROUP_CHILONZOR_02_ADMIN,
    GROUP_CHILONZOR_03_ADMIN,
    GROUP_CHILONZOR_HUB,
    GROUP_CHILONZOR_OPER,
    GROUP_MVD,
    ROLE_GROUPS,
)

User = get_user_model()


class FindingsForm(BaseStyledPlainForm):
    """Uch turdagi topilmalarni bir vaqtda, har qatorda bittadan qo'shish."""

    FINDING_FIELDS = (
        ("ip_values", ApkFinding.KIND_IP),
        ("domain_values", ApkFinding.KIND_DOMAIN),
        ("telegram_values", ApkFinding.KIND_TELEGRAM),
    )

    ip_values = forms.CharField(
        required=False,
        label=_("IP manzili"),
        help_text=_("Har qatorda bittadan IP manzil. Misol: 192.168.1.10 yoki 203.0.113.5:8080."),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    domain_values = forms.CharField(
        required=False,
        label=_("Domen"),
        help_text=_("Har qatorda bittadan domen. Misol: example.com."),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    telegram_values = forms.CharField(
        required=False,
        label=_("Telegram ID"),
        help_text=_("Har qatorda bittadan raqamli ID yoki @username. Misol: 5907562354 yoki @username."),
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean(self):
        cleaned = super().clean()
        parsed_values = {}
        for field_name, kind in self.FINDING_FIELDS:
            values, errors = parse_lines(kind, cleaned.get(field_name, ""))
            parsed_values[kind] = values
            if errors:
                self.add_error(
                    field_name,
                    "; ".join(f"{line}: {message}" for line, message in errors[:5])
                    + ("..." if len(errors) > 5 else ""),
                )
        if not self.errors and not any(parsed_values.values()):
            raise forms.ValidationError(translate("Kamida bitta qiymat kiriting."))
        cleaned["parsed_values"] = parsed_values
        return cleaned


class AnalysisNoteForm(BaseStyledPlainForm):
    analysis_note = forms.CharField(
        required=False,
        label=_("Tahlil izohi"),
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": _("Qanday tahlil qilindi, qayerdan topildi...")}
        ),
    )


class ReviewForm(BaseStyledPlainForm):
    note = forms.CharField(
        required=False,
        label=_("Izoh / kamchiliklar"),
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": _("Qaytarishda kamchiliklarni yozing")}
        ),
    )


class ReviewAssignmentForm(BaseStyledPlainForm):
    reviewer = forms.ModelChoiceField(
        queryset=Users.objects.none(),
        label=_("Chilonzor xodimi"),
        empty_label=_("Xodimni tanlang"),
    )

    def __init__(self, *args, reviewers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reviewer"].queryset = reviewers or Users.objects.none()
        self.fields["reviewer"].label_from_instance = lambda profile: (
            f"{profile} ({profile.account.username})"
        )


def use_floating_labels(form):
    """Suzuvchi yorliq CSS'i (:placeholder-shown) ishlashi uchun bo'sh placeholder."""
    for field in form.fields.values():
        field.widget.attrs.setdefault("placeholder", " ")


class ChilonzorEmployeeForm(BaseStyledPlainForm):
    manager = forms.ModelChoiceField(
        queryset=Users.objects.none(),
        label=_("Jamoa"),
        empty_label=_("Jamoani tanlang"),
    )
    username = forms.CharField(
        label=_("Login"),
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    first_name = forms.CharField(label=_("Ism"), max_length=100)
    last_name = forms.CharField(label=_("Familiya"), max_length=100)
    password1 = forms.CharField(
        label=_("Parol"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Parolni tasdiqlang"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, team_managers=None, **kwargs):
        super().__init__(*args, **kwargs)
        use_floating_labels(self)
        if team_managers is None:
            self.fields.pop("manager")
            return
        self.fields["manager"].queryset = team_managers
        self.fields["manager"].label_from_instance = self._manager_label

    @staticmethod
    def _manager_label(profile):
        groups = set(profile.account.groups.values_list("name", flat=True))
        team = (
            translate("Chilonzor Oper")
            if GROUP_CHILONZOR_02_ADMIN in groups
            else translate("Chilonzor Hub")
            if GROUP_CHILONZOR_03_ADMIN in groups
            else translate("Chilonzor")
        )
        return f"{team} - {profile} ({profile.account.username})"

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(translate("Bu login band, boshqasini kiriting."))
        return username

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", translate("Parollar bir xil emas."))
        elif password2:
            try:
                password_validation.validate_password(password2)
            except forms.ValidationError as exc:
                self.add_error("password2", exc)
        return cleaned

    def save(self, *, worker_group):
        account = User.objects.create_user(
            username=self.cleaned_data["username"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            password=self.cleaned_data["password1"],
            is_staff=False,
            is_active=True,
        )
        group, _created = Group.objects.get_or_create(name=worker_group)
        account.groups.add(group)
        return account


class AttachChilonzorEmployeeForm(BaseStyledPlainForm):
    employee = forms.ModelChoiceField(
        queryset=Users.objects.none(),
        label=_("Mavjud xodim"),
        empty_label=_("Xodimni tanlang"),
    )
    manager = forms.ModelChoiceField(
        queryset=Users.objects.none(),
        label=_("Jamoa"),
        empty_label=_("Jamoani tanlang"),
    )

    def __init__(self, *args, employees=None, team_managers=None, **kwargs):
        super().__init__(*args, **kwargs)
        use_floating_labels(self)
        self.fields["employee"].queryset = employees or Users.objects.none()
        self.fields["employee"].label_from_instance = lambda profile: (
            f"{profile} ({profile.account.username})"
        )
        if team_managers is None:
            self.fields.pop("manager")
        else:
            self.fields["manager"].queryset = team_managers
            self.fields["manager"].label_from_instance = ChilonzorEmployeeForm._manager_label


class KursantForm(BaseStyledForm):
    """Admin jadvalga yangi ustun (kursant) qo'shadi."""

    class Meta:
        model = Kursant
        fields = ["user", "kind", "team", "sort_order", "is_active"]
        widgets = {
            "team": forms.TextInput(attrs={"placeholder": _("Masalan: 1-guruh")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # MVD / Chilonzor xodimlari kursant bo'lmaydi - ular alohida rollar.
        queryset = (
            Users.objects.select_related("account")
            .filter(account__isnull=False)
            .exclude(account__groups__name__in=ROLE_GROUPS)
        )
        if self.instance and self.instance.pk:
            queryset = queryset.filter(
                Q(kursant_profile__isnull=True) | Q(kursant_profile=self.instance)
            )
        else:
            queryset = queryset.filter(kursant_profile__isnull=True)
        self.fields["user"].queryset = queryset.order_by("first_name", "last_name")
        self.fields["user"].label_from_instance = lambda profile: str(profile)


class PairedValuesFormMixin:
    def __init__(self, *args, initial_pairs=None, row_prefix="pair", **kwargs):
        super().__init__(*args, **kwargs)
        self.pair_prefix = row_prefix
        telegram_ids = self._get_list("telegram_id")
        values = self._get_list("value")
        if self.is_bound:
            row_count = max(len(telegram_ids), len(values), 1)
            self.pair_rows = [
                {
                    "telegram_id": telegram_ids[index] if index < len(telegram_ids) else "",
                    "value": values[index] if index < len(values) else "",
                }
                for index in range(row_count)
            ]
        else:
            self.pair_rows = [
                {"telegram_id": row.get("telegram_id", ""), "value": row.get("value", "")}
                for row in (initial_pairs or [{"telegram_id": "", "value": ""}])
            ]

    def _get_list(self, key):
        if hasattr(self.data, "getlist"):
            return self.data.getlist(key)
        value = self.data.get(key, [])
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value] if value else []

    def clean(self):
        cleaned = super().clean()
        pairs = []
        for index, row in enumerate(self.pair_rows, start=1):
            telegram_id = str(row["telegram_id"]).strip()
            value = str(row["value"]).strip()
            if not telegram_id and not value:
                continue
            if not telegram_id or not value:
                self.add_error(
                    None,
                    translate(
                        "{row}-qatorda Telegram ID va qiymat ikkalasini ham to'ldiring.",
                        row=index,
                    ),
                )
                continue
            if len(telegram_id) > 100 or len(value) > 255:
                self.add_error(
                    None,
                    translate("Telegram ID 100, qiymat esa 255 belgidan oshmasin."),
                )
                continue
            pairs.append({"telegram_id": telegram_id, "value": value})

        if not pairs and not self.non_field_errors():
            self.add_error(None, translate("Kamida bitta Telegram ID va qiymat juftini kiriting."))
        cleaned["pairs"] = pairs
        return cleaned


class OsintTaskForm(PairedValuesFormMixin, BaseStyledPlainForm):
    title = forms.CharField(max_length=200, label=_("Sarlavha"))
    description = forms.CharField(
        label=_("Tavsif"),
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class OsintTaskResultForm(PairedValuesFormMixin, BaseStyledPlainForm):
    pass


class ApiClientForm(BaseStyledPlainForm):
    name = forms.CharField(
        max_length=100,
        label=_("Nomi"),
        widget=forms.TextInput(attrs={"placeholder": _("Masalan: Telegram bot")}),
    )
    user = forms.ModelChoiceField(
        queryset=Users.objects.none(),
        label=_("MVD hisobi"),
        help_text=_("Bot yuborgan hamma yozuvlarda manba sifatida shu MVD ko'rinadi."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            Users.objects.select_related("account")
            .filter(account__groups__name__iexact=GROUP_MVD, account__is_active=True)
            .distinct()
            .order_by("first_name", "last_name")
        )
        self.fields["user"].label_from_instance = lambda profile: (
            f"{profile} ({profile.account.username})"
        )

    def save(self):
        client, raw_token = ApiClient.create_with_token(
            self.cleaned_data["name"], self.cleaned_data["user"]
        )
        return client, raw_token
