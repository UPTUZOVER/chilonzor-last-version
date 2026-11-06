"""Botdan APK fayl yoki havola qabul qiladigan API.

POST /api/apk/
Content-Type: application/json

Bu endpoint ochiq: token, login yoki parol talab qilinmaydi.

APK uchun multipart/form-data ichida `file`, JSON ichida `file_base64` yuboriladi.
Havola uchun JSON yoki multipart/form-data ichida `source_type=link` va `url` yuboriladi. `type` eski
formatda Telegram chat turini anglatadi; APK/havola turi uchun `source_type` ishlating.
Profil va chat ma'lumotlari ixtiyoriy. Har so'rovda APK fayli yoki havoladan bittasi
bo'lishi shart.
"""

import base64
import binascii
import hashlib
import json
from functools import wraps
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from .models import ApkSubmission
from .workflow import record_received

DEFAULT_MAX_UPLOAD_MB = 200
ZIP_MAGIC = b"PK\x03\x04"
URL_VALIDATOR = URLValidator(schemes=["http", "https"])
LINK_TYPE_NAMES = {"link", "url", "havola"}
APK_TYPE_NAMES = {"apk", "akp", "file", "fayl"}


def _error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def public_api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = HttpResponse(status=204) if request.method == "OPTIONS" else view(request, *args, **kwargs)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    return wrapped


def _request_data(request):
    if request.content_type != "application/json":
        return request.POST, None
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "JSON formati noto'g'ri."
    if not isinstance(payload, dict):
        return None, "JSON obyekti yuborilishi kerak."
    return payload, None


def _get(data, *names):
    keys = {str(key).strip().lower().replace(" ", "_"): key for key in data.keys()}
    for name in names:
        key = keys.get(str(name).strip().lower().replace(" ", "_"), name)
        value = data.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def _optional_int(data, field, fallback=None, aliases=()):
    raw = _get(data, field, *aliases) or _get(fallback or {}, field, *aliases)
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        return int(str(raw).strip()), None
    except (TypeError, ValueError):
        return None, f"{field} butun son bo'lishi kerak."


def _optional_datetime(data, field, aliases=()):
    raw = _get(data, field, *aliases)
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        value = parse_datetime(str(raw).strip())
    except (OverflowError, ValueError):
        value = None
    if value is None:
        return None, f"{field} ISO 8601 sana-vaqt formatida bo'lishi kerak."
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value, None


def _source_type(data, uploaded, source_url):
    requested = str(_get(data, "source_type", "submission_type", "content_type")).strip().lower()
    legacy_type = str(_get(data, "type") or "").strip().lower()
    if not requested and legacy_type in LINK_TYPE_NAMES | APK_TYPE_NAMES:
        requested = legacy_type
    if requested:
        if requested in LINK_TYPE_NAMES:
            return ApkSubmission.SOURCE_LINK, None
        if requested in APK_TYPE_NAMES:
            return ApkSubmission.SOURCE_APK, None
        return None, "`source_type` qiymati `apk` yoki `link` bo'lishi kerak."
    if uploaded is not None:
        return ApkSubmission.SOURCE_APK, None
    if source_url:
        return ApkSubmission.SOURCE_LINK, None
    return None, "APK uchun `file`, havola uchun `url` maydonini yuboring."


def _validate_url(raw_url):
    source_url = str(raw_url or "").strip()
    if not source_url:
        return "", "Havola (`url`) yuborilmagan."
    if len(source_url) > 2048:
        return "", "Havola 2048 belgidan uzun bo'lmasligi kerak."
    try:
        URL_VALIDATOR(source_url)
        parts = urlsplit(source_url)
    except (ValidationError, ValueError):
        return "", "Havola http:// yoki https:// bilan boshlanishi kerak."
    if not parts.hostname or parts.username or parts.password:
        return "", "Havola manzili noto'g'ri."
    return source_url, None


def _url_file_name(source_url):
    path_name = unquote(urlsplit(source_url).path.rsplit("/", 1)[-1]).strip()
    return path_name[:255] or urlsplit(source_url).hostname or "APK havolasi"


def _max_upload_bytes():
    return int(getattr(settings, "APK_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB)) * 1024 * 1024


def _base64_upload(encoded, file_name):
    value = str(encoded or "").strip()
    if value.startswith("data:"):
        header, separator, value = value.partition(",")
        if not separator or ";base64" not in header.lower():
            return None, "`file_base64` data URI formati noto'g'ri.", 400
    value = "".join(value.split())
    max_bytes = _max_upload_bytes()
    max_encoded_length = ((max_bytes + 2) // 3) * 4
    if len(value) > max_encoded_length:
        return None, "Fayl juda katta.", 413
    try:
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None, "`file_base64` qiymati noto'g'ri Base64.", 400
    if len(content) > max_bytes:
        return None, "Fayl juda katta.", 413
    upload_name = str(file_name or "upload.apk").strip()[:255] or "upload.apk"
    return SimpleUploadedFile(upload_name, content), None, None


@csrf_exempt
@public_api
def receive_apk_view(request):
    if request.method == "GET":
        return JsonResponse(
            {
                "ok": True,
                "method": "POST",
                "content_type": "application/json",
                "authentication_required": False,
                "required": ["file_base64 (APK uchun) yoki url (havola uchun)"],
                "optional": [
                    "file_name", "hash_value", "sender_id", "sender_username",
                    "chat_id", "chat_title", "created_at", "source_type",
                ],
            }
        )
    if request.method != "POST":
        return _error("Faqat POST so'rovi qabul qilinadi.", status=405)

    data, error = _request_data(request)
    if error:
        return _error(error)

    uploaded = _get(request.FILES, "file") or None
    if uploaded is None:
        encoded_file = _get(data, "file_base64", "file_data")
        if encoded_file:
            upload_name = _get(data, "file_name", "filename") or "upload.apk"
            uploaded, error, status = _base64_upload(encoded_file, upload_name)
            if error:
                return _error(error, status=status)
    raw_url = _get(data, "source_url", "url", "link", "file_url")
    if not raw_url:
        file_value = _get(data, "file")
        if isinstance(file_value, str) and file_value.strip().lower().startswith(("http://", "https://")):
            raw_url = file_value
    source_type, error = _source_type(data, uploaded, raw_url)
    if error:
        return _error(error)

    chat_info = _get(data, "chat_info")
    if not isinstance(chat_info, dict):
        chat_info = {}
    user_id, error = _optional_int(data, "user_id", aliases=("sender_id",))
    if error:
        return _error(error)
    chat_id, error = _optional_int(data, "chat_id", chat_info)
    if error:
        return _error(error)
    source_created_at, error = _optional_datetime(data, "created_at")
    if error:
        return _error(error)
    source_hash = str(_get(data, "hash_value") or "").strip()
    if len(source_hash) > 255:
        return _error("`hash_value` 255 belgidan oshmasligi kerak.")

    if source_type == ApkSubmission.SOURCE_APK:
        if uploaded is None:
            return _error("APK uchun multipart `file` yoki JSON `file_base64` yuboring.")
        if raw_url:
            return _error("Bir so'rovda APK fayl yoki havoladan bittasini yuboring.")
        file_name = (uploaded.name or "").strip()
        if not file_name.lower().endswith(".apk"):
            return _error("Faqat .apk fayl qabul qilinadi.")

        max_bytes = _max_upload_bytes()
        if uploaded.size > max_bytes:
            return _error("Fayl juda katta.", status=413)

        header = uploaded.read(4)
        uploaded.seek(0)
        if header != ZIP_MAGIC:
            return _error("Fayl haqiqiy APK (ZIP) emas.")

        digest = hashlib.sha256()
        for chunk in uploaded.chunks():
            digest.update(chunk)
        sha256 = digest.hexdigest()
        uploaded.seek(0)
        source_url = ""
        file_size = uploaded.size
    else:
        if uploaded is not None:
            return _error("Havola yuborilganda `file` faylini qo'shmang.")
        source_url, error = _validate_url(raw_url)
        if error:
            return _error(error)
        sha256 = ""
        file_size = 0
        file_name = str(_get(data, "file_name", "filename") or _url_file_name(source_url)).strip()[:255]

    legacy_type = str(_get(data, "type") or "").strip()
    media_type_values = LINK_TYPE_NAMES | APK_TYPE_NAMES
    chat_type = _get(data, "chat_type") or _get(chat_info, "type")
    if not chat_type and legacy_type.lower() not in media_type_values:
        chat_type = legacy_type

    if source_type == ApkSubmission.SOURCE_APK:
        first_copy = ApkSubmission.objects.filter(
            source_type=ApkSubmission.SOURCE_APK, sha256=sha256
        ).order_by("created_at", "pk").first()
    else:
        first_copy = ApkSubmission.objects.filter(
            source_type=ApkSubmission.SOURCE_LINK, source_url=source_url
        ).order_by("created_at", "pk").first()

    with transaction.atomic():
        submission = ApkSubmission(
            sender_name=str(_get(data, "profile_name", "name"))[:255],
            sender_username=str(_get(data, "sender_username", "username"))[:64],
            sender_user_id=user_id,
            source_hash=source_hash,
            source_created_at=source_created_at,
            chat_title=str(_get(data, "chat_title", "title") or _get(chat_info, "title"))[:255],
            chat_type=str(chat_type)[:32],
            chat_id=chat_id,
            source_type=source_type,
            source_url=source_url,
            file_name=file_name[:255],
            file_size=file_size,
            sha256=sha256,
            duplicate_of=first_copy,
            source=None,
        )
        if uploaded is not None:
            submission.file.save(file_name, uploaded, save=False)
        submission.save()
        record_received(submission)

    return JsonResponse(
        {
            "ok": True,
            "id": submission.pk,
            "status": submission.status,
            "source_type": submission.source_type,
            "file_name": submission.file_name,
            "url": submission.source_url or None,
            "sha256": submission.sha256 or None,
            "hash_value": submission.source_hash or None,
            "created_at": submission.source_created_at.isoformat() if submission.source_created_at else None,
            "received_at": submission.created_at.isoformat(),
            "duplicate_of": first_copy.pk if first_copy else None,
        },
        status=201,
    )
