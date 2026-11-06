# Raqamli Qalqon — APK tahlil tizimi

Telegram botdan API orqali kelgan APK fayllarni kursantlar tahlil qiladi (ichidan IP, domen va
Telegram ID topadi), natijani **Chilonzor** roliga yuboradi, Chilonzor esa qabul qiladi yoki
kamchiliklarini yozib qaytaradi. MVD hammasini ko'rib turadi.

## Rollar
- **Admin** (`is_staff`) - hamma narsa: kursantlar va foydalanuvchilar.
- **APK kursant** - jadvalda `apk_kursant` turi bilan beriladi. API'dan kelgan APK ishlarini oladi,
  IP / domen / Telegram ID kiritadi va Chilonzorga yuboradi. Qaytarilsa tuzatib qayta yuboradi.
- **OSINT kursant** - jadvalda `osint_kursant` turi bilan beriladi. APK ishlarini ko'rmaydi;
  Chilonzor Oper yuborgan Akademiya topshiriqlarini ko'radi.
- **MVD** - hammasini ko'radi (faqat o'qish).
- **Chilonzor admin 01** (`chilonzor_01_admin`) - barcha jamoa va ishlarni ko'radi, ishni istalgan xodimga biriktira oladi.
- **Chilonzor admin 02/03** (`chilonzor_02_admin`, `chilonzor_03_admin`) - o'z jamoasiga xodim qo'shadi va ishni faqat o'z xodimlariga biriktiradi. 02 xodimlari `chilonzor_oper`, 03 xodimlari `chilonzor_hub` guruhiga tushadi; 01 jamoani tanlaydi.
- **Chilonzor xodimi** (`Chilonzor` guruhi) - faqat o'ziga biriktirilgan ishlarni ko'radi va qabul qiladi yoki kamchilik bilan kursantga qaytaradi; navbatdan o'zi ish ola olmaydi.
- **Chilonzor Oper** (`chilonzor_oper`) - Chilonzor kabi APK ishlarini ko'radi va qaror qiladi;
  Telegram ID/qiymat juftlari, sarlavha va tavsif bilan Akademiyaga OSINT topshirig'i yuboradi.
- **Chilonzor Hub** (`chilonzor_hub`) - admin 03 boshqaradigan Chilonzor APK ko'rib chiqish jamoasi.

Oqim: `Yangi -> Kursant tahlil qilmoqda -> Chilonzor admin xodimga biriktiradi -> Xodim ko'rib chiqadi -> Qabul qilindi`
(yoki `Qaytarildi` -> kursant tuzatadi -> qayta yuboradi). Har bir o'tish "Ish tarixi"da saqlanadi.

OSINT oqimi: Chilonzor Oper sarlavha, tavsif va Telegram ID/qiymat juftlari bilan topshiriq yuboradi.
OSINT kursant topshiriqni oladi va natija juftlarini operatorlarga yuboradi. Bir operator ishni olib
tasdiqlasa kursantga 10 ball qo'shiladi; qaytarsa kursant tuzatib qayta yuboradi.

## Dashboard va hisobot
Har bir rol o'ziga mos dashboardni ko'radi: admin umumiy tizim va kursantlar faoliyatini, MVD kelgan APKlar va manbalarni, Chilonzor ko'rib chiqish navbatini, kursant esa o'z ishlarini kuzatadi. Dashboardda holatlar va topilmalar doira diagrammada, kunlik faollik ustunli diagrammada ko'rsatiladi. Grafik davrini 7, 30 yoki 90 kunga o'zgartirib, shu davr hisobotini Word (`.docx`) formatida yuklab olish mumkin.

`/apk/team/` Chilonzor jamoa sahifasida admin 01 barcha xodimlarni, admin 02/03 o'z jamoasini, xodim esa o'z ish tarixini ko'radi. Reyting oxirgi 30 kunda qabul qilingan ishlar o'rtachasiga nisbatan hisoblanadi. Xodim ismi yonidagi strelka uning ishlarini ochadi; ish ichida topilmalar va harakatlar tarixi ko'rinadi.

## Botdan APK qabul qilish (API)
`POST /api/apk/` ochiq. Yuboruvchi login, parol yoki API token yubormaydi. Brauzerda shu manzilni
ochish GET so'rovini yuboradi va qabul qilinadigan maydonlar ro'yxatini ko'rsatadi. Fayl yuborish:

```
POST /api/apk/
Content-Type: multipart/form-data

file=<APK fayl>            APK yuborilganda majburiy, .apk (ZIP), eng ko'pi APK_MAX_UPLOAD_MB
source_type=apk            ixtiyoriy; file bo'lsa avtomatik aniqlanadi
profile_name=Ўткир         yuborgan profil nomi
username=@salom6233        yuborgan username
user_id=5907562354         yuborgan user ID
title=My music             APK yuborilgan guruh nomi
chat_type=supergroup       guruh turi (eski so'rovlar uchun type=supergroup ham qabul qilinadi)
chat_id=-1003542328393     guruh ID
```

APK fayl o'rniga havola yuborish uchun JSON (`application/json`) yoki multipart so'rovda `source_type=link` va `url` jo'nating. Havola Telegram xabariga biriktirilgan bo'lsa, `type` maydoni bilan chat turini aralashtirmaslik uchun guruh ma'lumotlarini `chat_info` ichida yuboring:

```json
{
  "profile_name": "Ўткир",
  "username": "@salom6233",
  "user_id": 5907562354,
  "source_type": "link",
  "url": "https://example.org/SafarAI_Kameralar_BEPUL.apk",
  "file_name": "SafarAI_Kameralar_BEPUL.apk",
  "chat_info": {
    "title": "My music",
    "type": "supergroup",
    "chat_id": -1003542328393
  }
}
```

APK faylni JSON ichida yuborish uchun fayl baytlarini Base64 qilib, `file_base64` maydoniga joylang:

```json
{
  "sender_id": 5907562354,
  "sender_username": "@salom6233",
  "chat_id": -1003542328393,
  "chat_title": "My music",
  "file_name": "SafarAI_Kameralar_BEPUL.apk",
  "hash_value": "MVD yuborgan xesh qiymati",
  "created_at": "2026-11-05T12:30:00+05:00",
  "file_base64": "<APK faylining Base64 qiymati>",
  "source_type": "apk"
}
```

MVD uchun `POST /api/apk/` aynan `sender_id`, `sender_username`, `chat_id`, `chat_title`, `file_base64`, `file_name`, `hash_value` va `created_at` maydonlarini qabul qiladi. `hash_value` MVD yuborgan ko'rinishida alohida saqlanadi; APK faylining haqiqiy SHA-256 xeshini tizim o'zi hisoblaydi. `created_at` ISO 8601 formatidagi MVD vaqti sifatida saqlanadi, tizimga kelgan vaqt esa alohida qoladi. Profil/guruh ma'lumotlari, `hash_value` va `created_at` bo'sh bo'lishi mumkin; APK uchun `file_base64` majburiy.

Aniq POST namunasi (PowerShell; token, login va parol kerak emas):

```powershell
$apkPath = 'C:\path\Video_mp4.apk'
$payload = @{
    file_base64     = [Convert]::ToBase64String([IO.File]::ReadAllBytes($apkPath))
    file_name       = 'Video_mp4.apk'
    hash_value      = '1cd4814e8282b54bcdbb0185daba2ca102d3a0e6ac96f9ca9238e1c74e2330bd'
    sender_id       = '5907562354'
    sender_username = 'salom6233'
    chat_id         = '-1003731598614'
    chat_title      = 'Test apk'
    created_at      = '2026-11-06T04:37:44.834901+00:00'
} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://192.168.1.115:9090/api/apk/' -Method Post -ContentType 'application/json' -Body $payload
```

`file_base64` ga `'base_64'` matnini yozmang: haqiqiy APK baytlarini Base64 qilib yuboring. Fayl `.apk` bo'lishi va APK/ZIP mazmuniga ega bo'lishi kerak.

Faylni Base64 qilish (PowerShell): `[Convert]::ToBase64String([IO.File]::ReadAllBytes('SafarAI_Kameralar_BEPUL.apk'))`. Fayl katta bo'lsa, JSON o'rniga `multipart/form-data` orqali `file` yuborish tejamkorroq.

`source_type` qiymatlari: `apk` yoki `link` (`havola` ham qabul qilinadi). Havola tizimda saqlanib, ish sahifasi va ro'yxatida bosiladigan bo'ladi; server URL'dan faylni o'zi yuklab olmaydi.
Profil va chat maydonlari (`sender_id`/`user_id`, `sender_username`/`username`, `chat_title`/`title`, `chat_type`, `chat_id`), `hash_value` va `created_at` ixtiyoriy; bo'sh qiymatlar qabul qilinadi. `file_name` ham ixtiyoriy: APK uchun `upload.apk`, havola uchun URL yo'lidagi nom ishlatiladi. Fayl yuborishda `file` yoki `file_base64` maydonidan biri, havola yuborishda `url` kerak.

Javob `201`da yozuv IDsi, holati va manba turi qaytadi. APK uchun `sha256` tizim hisoblagan xesh, `hash_value` MVD yuborgan xesh bo'ladi. Javobdagi `created_at` MVD vaqti, `received_at` tizim qabul qilgan vaqtidir. Havola uchun `url` qaytadi (`sha256` `null` bo'ladi). Bir xil APK SHA-256 yoki bir xil havola qayta kelsa ham yangi yozuv ochiladi; `duplicate_of` avvalgi yozuv ID sini ko'rsatadi va kursant oldingi topilmalarni ko'chira oladi.
Xato: `400` (maydon/fayl noto'g'ri), `413` (fayl katta), `405` (POST/GET/OPTIONS emas).
Bir xil fayl (SHA-256) qayta kelsa ham yangi yozuv ochiladi, `duplicate_of` oldingi yozuvni ko'rsatadi
va kursant oldingi topilmalarni bir tugma bilan ko'chira oladi.

APK fayllar ochiq `/media/` orqali **berilmaydi**; faqat tizimga kirgan, ruxsati bor foydalanuvchi
`Yuklab olish` orqali oladi. Fayl zararli bo'lishi mumkin - faqat izolyatsiyalangan muhitda oching.

## Tarkibi
- `apk/` - asosiy ilova: modellar, API (`api.py`), ish oqimi (`workflow.py`), tekshiruv (`parsing.py`), sahifalar.
- `app/` - umumiy asos: login/ro'yxatdan o'tish, foydalanuvchilar va guruhlar, ichki xabarlar, UI tarjimasi (uz/en).
- `chilonzor/` - Django sozlamalari va URL'lar.

## Ishga tushirish (Windows)
`ishga_tushir.bat` - venv yaratadi, kutubxonalarni o'rnatadi, migratsiya qiladi va serverni ochadi
(`http://127.0.0.1:8000/apk/works/`).

Qo'lda:
```
python -m venv winenv && winenv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
`python manage.py demo_data` - har bir rolega bittadan demo hisob (admin1, mvd1, kursant1, osint1, chilonzor1, chilonzor_oper1, chilonzor_01_admin, chilonzor_02_admin, chilonzor_03_admin) va namunaviy APK ishlar;
`--clear` bilan o'chiriladi. Baza: SQLite (`chilonzor_db.sqlite3`), lokalda ham Docker ichida ham.
Migratsiyalar MVD va Chilonzor guruhlarini avtomatik yaratadi.

Eslatma: avvalgi (karta bloklash) versiyada ishlatilgan eski baza bu versiyaga mos kelmaydi -
`chilonzor_db.sqlite3` faylini o'chirib, `migrate` ni qaytadan ishga tushiring.
