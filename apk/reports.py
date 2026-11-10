"""Statistika sahifasidan Word (DOCX) ma'lumotnoma yasaydi (tashqi kutubxonasiz).

Hujjat rasmiy xizmat ma'lumotnomasi ko'rinishida: Times New Roman 14 pt, A4,
raqamlangan bo'limlar, raqamlar jumlalar bilan izohlanadi, oxirida xulosa va
imzo bloki. Jadvallar oddiy (ingichka chegara, kulrang sarlavha qatori).
"""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape

from django.utils import timezone


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

FONT = "Times New Roman"
BODY_SIZE = 28  # 14 pt
TABLE_SIZE = 24  # 12 pt
TEXT_WIDTH = 9354  # A4 kengligi (11906) - chap 30 mm (1701) - o'ng 15 mm (851)

ROLE_UNITS = {
    "admin": "Tizim ma'muriyati",
    "mvd": "IIV mas'ul bo'linmasi",
    "chilonzor": "Chilonzor ko'rib chiqish bo'limi",
    "kursant": "APK tahlil kursanti",
}


def _text(value):
    text = str(value if value is not None else "")
    text = "".join(
        char
        for char in text
        if char in "\t\n\r"
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
    )
    return escape(text)


def _run(text, bold=False, italic=False, size=None, caps=False):
    props = [f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>']
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if caps:
        props.append("<w:caps/>")
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    return f'<w:r><w:rPr>{"".join(props)}</w:rPr><w:t xml:space="preserve">{_text(text)}</w:t></w:r>'


def _p(runs, align="both", indent=True, before=0, after=0, keep_next=False, tabs=None):
    """Paragraf. runs - matn yoki _run() natijalari ro'yxati."""
    if isinstance(runs, str):
        runs = [_run(runs)]
    props = [f'<w:jc w:val="{align}"/>', f'<w:spacing w:before="{before}" w:after="{after}"/>']
    if indent:
        props.append('<w:ind w:firstLine="709"/>')
    if keep_next:
        props.append("<w:keepNext/>")
    if tabs:
        props.append("<w:tabs>" + "".join(f'<w:tab w:val="{kind}" w:pos="{pos}"/>' for kind, pos in tabs) + "</w:tabs>")
    return f'<w:p><w:pPr>{"".join(props)}</w:pPr>{"".join(runs)}</w:p>'


def _heading(number, title):
    return _p([_run(f"{number}. {title}", bold=True)], align="left", indent=True, before=200, after=80, keep_next=True)


def _count(value, unit="ta"):
    return f"{value} {unit}"


def _percent(part, total):
    return round(part * 100 / total) if total else 0


def _cell(value, width, header=False, align="left"):
    shade = '<w:shd w:val="clear" w:color="auto" w:fill="EDEDED"/>' if header else ""
    return (
        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}<w:vAlign w:val="center"/></w:tcPr>'
        f'<w:p><w:pPr><w:jc w:val="{"center" if header else align}"/><w:spacing w:before="20" w:after="20"/></w:pPr>'
        f"{_run(value, bold=header, size=TABLE_SIZE)}</w:p></w:tc>"
    )


def _table(headers, rows, widths, aligns=None):
    """Oddiy jadval: ingichka qora chegara, kulrang sarlavha qatori, birinchi ustun - tartib raqami."""
    aligns = aligns or ["left"] * len(headers)
    scale = TEXT_WIDTH / sum(widths)
    widths = [round(w * scale) for w in widths]
    widths[-1] += TEXT_WIDTH - sum(widths)
    border = 'w:val="single" w:sz="4" w:space="0" w:color="000000"'
    grid = "".join('<w:gridCol w:w="%d"/>' % w for w in widths)
    xml = (
        f'<w:tbl><w:tblPr><w:tblW w:w="{TEXT_WIDTH}" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
        f"<w:tblBorders><w:top {border}/><w:left {border}/><w:bottom {border}/><w:right {border}/>"
        f"<w:insideH {border}/><w:insideV {border}/></w:tblBorders>"
        '<w:tblCellMar><w:left w:w="85" w:type="dxa"/><w:right w:w="85" w:type="dxa"/></w:tblCellMar>'
        f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>"
    )
    xml += '<w:tr><w:trPr><w:tblHeader/></w:trPr>' + "".join(
        _cell(h, widths[i], header=True) for i, h in enumerate(headers)
    ) + "</w:tr>"
    for row in rows:
        xml += "<w:tr><w:trPr><w:cantSplit/></w:trPr>" + "".join(
            _cell(value, widths[i], align=aligns[i]) for i, value in enumerate(row)
        ) + "</w:tr>"
    # Jadvaldan keyin kichik bo'shliq.
    return xml + "</w:tbl>" + _p("", indent=False, after=60)


def _numbered(rows):
    return [[f"{index}."] + list(row) for index, row in enumerate(rows, start=1)]


def _status_counts(context):
    return {row.get("status"): row["count"] for row in context["chart_rows"]}


def _summary_paragraphs(context):
    """1-bo'lim: umumiy holat - raqamlar jumlalar bilan."""
    role = context["role"]
    kpis = context["kpis"]
    period = f"{context['period_start']:%d.%m.%Y}–{context['period_end']:%d.%m.%Y}"
    counts = _status_counts(context)
    total = context["chart_total"]
    paragraphs = []

    if role == "chilonzor":
        # kpis tartibi dashboard_data.py da: navbat, kechikkan, davrdagi qarorlar,
        # qabul darajasi, o'rtacha vaqt, bugungi qarorlar, qaytarilganlar.
        queue, overdue, average = kpis[0]["value"], kpis[1]["value"], kpis[4]["value"]
        accepted, returned = counts.get("accepted", 0), counts.get("returned", 0)
        if total:
            paragraphs.append(
                f"Hisobot davrida ({period}) Chilonzor bo'limi tomonidan jami {_count(total)} APK ishi "
                f"bo'yicha qaror qabul qilindi. Shundan {_count(accepted)} ish ({_percent(accepted, total)}%) "
                f"tasdiqlandi, {_count(returned)} ish ({_percent(returned, total)}%) aniqlangan kamchiliklar "
                f"bilan qayta ishlash uchun kursantga qaytarildi."
            )
            paragraphs.append(
                f"Ishlarning kursant tomonidan yuborilgan vaqtdan qaror qabul qilingunga qadar o'rtacha "
                f"ko'rib chiqish muddati {average}ni tashkil etdi."
            )
        else:
            paragraphs.append(f"Hisobot davrida ({period}) Chilonzor bo'limi tomonidan qaror qabul qilingan ish qayd etilmadi.")
        if queue:
            text = f"Hisobot tayyorlangan vaqtda ko'rib chiqish navbatida {_count(queue)} ish turibdi"
            text += f", ulardan {_count(overdue)} tasi 48 soatdan ortiq kutmoqda." if overdue else ", muddati o'tgan ish yo'q."
            paragraphs.append(text)
        else:
            paragraphs.append("Hisobot tayyorlangan vaqtda ko'rib chiqish navbatida kutayotgan ish yo'q.")

    elif role == "kursant":
        if total:
            parts = [f"{row['label'].lower()} — {row['count']}" for row in context["chart_rows"] if row["count"]]
            paragraphs.append(
                f"Hisobot tayyorlangan vaqtda kursantga jami {_count(total)} APK ishi biriktirilgan bo'lib, "
                f"ularning holati quyidagicha: {', '.join(parts)}."
            )
        else:
            paragraphs.append("Hisobot tayyorlangan vaqtda kursantga biriktirilgan APK ishi yo'q.")
        paragraphs.append(
            f"Hisobot davrida ({period}) Chilonzor bo'limiga {_count(context['trend_total'])} tahlil natijasi yuborilgan."
        )

    else:  # admin, mvd
        paragraphs.append(
            f"Hisobot davrida ({period}) tizimga Telegram bot orqali {_count(context['trend_total'])} APK fayl "
            f"(havola) kelib tushdi. Tizimda jami {_count(total)} APK ishi ro'yxatga olingan."
        )
        if total:
            accepted, returned = counts.get("accepted", 0), counts.get("returned", 0)
            waiting = counts.get("new", 0) + counts.get("in_progress", 0) + counts.get("sent", 0)
            paragraphs.append(
                f"Ulardan {_count(accepted)} ish ({_percent(accepted, total)}%) bo'yicha tahlil yakunlanib, "
                f"Chilonzor bo'limi tomonidan tasdiqlangan, {_count(returned)} ish qayta ishlash uchun "
                f"qaytarilgan, {_count(waiting)} ish esa ishlov berish bosqichida."
            )

    peak = context.get("trend_peak")
    if peak:
        paragraphs.append(
            f"Davr mobaynida eng yuqori faollik {peak['day']:%d.%m.%Y} kuni kuzatildi ({_count(peak['count'])})."
        )
    return paragraphs


def _conclusions(context):
    role = context["role"]
    counts = _status_counts(context)
    total = context["chart_total"]
    items = []
    if role == "chilonzor":
        overdue = context["kpis"][1]["value"]
        if overdue:
            items.append(f"48 soatdan ortiq kutayotgan {_count(overdue)} ish bo'yicha qaror qabul qilinishini tezlashtirish lozim.")
    returned = counts.get("returned", 0)
    if total and _percent(returned, total) >= 30:
        items.append(
            f"Qaytarilgan ishlar ulushi yuqori ({_percent(returned, total)}%). Kursantlar bilan tahlil sifati "
            f"yuzasidan qo'shimcha tushuntirish ishlarini olib borish maqsadga muvofiq."
        )
    if role in ("admin", "mvd") and counts.get("new"):
        items.append(f"Kursantlar tomonidan hali olinmagan {_count(counts['new'])} yangi ish mavjud, ularni taqsimlash zarur.")
    if not any(group["items"] for group in context["repeated_groups"]):
        items.append("Bir nechta APK faylda takrorlangan IP manzil, domen yoki Telegram ID aniqlanmadi.")
    if not items:
        items.append("Hisobot davrida ish jarayonida jiddiy kamchiliklar aniqlanmadi.")
    return items


def _report_body(context):
    now = timezone.localtime()
    role = context["role"]
    period = f"{context['period_start']:%d.%m.%Y} – {context['period_end']:%d.%m.%Y}"
    parts = [
        _p([_run("O'zbekiston Respublikasi Ichki ishlar vazirligi", bold=True, caps=True, size=24)], align="center", indent=False),
        _p([_run("«Raqamli Qalqon» APK tahlil tizimi", size=24)], align="center", indent=False, after=360),
        _p([_run("Ma'lumotnoma", bold=True, caps=True)], align="center", indent=False, after=60),
        _p(
            [_run(f"{ROLE_UNITS.get(role, '')} faoliyati to'g'risida ({period}, {context['period_days']} kun)", bold=True)],
            align="center", indent=False, after=240,
        ),
        _p([_run("Toshkent sh."), _run("\t"), _run(f"{now:%d.%m.%Y} y.")], indent=False, after=240, tabs=[("right", TEXT_WIDTH)]),
    ]

    section = 1
    parts.append(_heading(section, "Umumiy holat"))
    parts.extend(_p(text) for text in _summary_paragraphs(context))

    section += 1
    parts.append(_heading(section, "Asosiy ko'rsatkichlar"))
    parts.append(
        _table(
            ["№", "Ko'rsatkich", "Qiymat", "Izoh"],
            _numbered([[item["label"], item["value"], item["hint"]] for item in context["kpis"]]),
            [6, 38, 14, 42],
            ["center", "left", "center", "left"],
        )
    )

    section += 1
    parts.append(_heading(section, "Qarorlar taqsimoti" if role == "chilonzor" else "Ishlar holati bo'yicha taqsimot"))
    rows = [[row["label"], row["count"], f"{row['share']}%"] for row in context["chart_rows"]]
    rows.append(["Jami", context["chart_total"], "100%" if context["chart_total"] else "0%"])
    parts.append(_table(["№", "Holat", "Soni", "Ulushi"], _numbered(rows[:-1]) + [[""] + rows[-1]], [6, 54, 20, 20], ["center", "left", "center", "center"]))

    section += 1
    parts.append(_heading(section, context["trend_title"]))
    active_days = [item for item in context["daily"] if item["count"]]
    if active_days:
        parts.append(_p(
            f"Hisobot davrining {context['period_days']} kunidan {len(active_days)} kunda faollik qayd etildi, "
            f"jami {_count(context['trend_total'])}. Faollik bo'lgan kunlar:"
        ))
        parts.append(_table(
            ["№", "Sana", "Soni"],
            _numbered([[f"{item['day']:%d.%m.%Y}", item["count"]] for item in active_days]),
            [6, 60, 34], ["center", "left", "center"],
        ))
    else:
        parts.append(_p("Hisobot davrida faollik qayd etilmadi."))

    section += 1
    if role == "admin":
        parts.append(_heading(section, "Kursantlar faoliyati"))
        rows = [[row["name"], row["active"], row["accepted"], row["returned"]] for row in context["performance_rows"]]
        parts.append(
            _table(["№", "Kursant F.I.Sh.", "Ishlovda", "Tasdiqlangan", "Qaytarilgan"], _numbered(rows), [6, 46, 16, 16, 16],
                   ["center", "left", "center", "center", "center"])
            if rows else _p("Faol kursantlar ro'yxatga olinmagan.")
        )
    elif role == "mvd":
        parts.append(_heading(section, "APK yuborgan manbalar"))
        rows = [[row["name"], row["count"]] for row in context["source_rows"]]
        parts.append(
            _table(["№", "Manba", "APK soni"], _numbered(rows), [6, 64, 30], ["center", "left", "center"])
            if rows else _p("Manbalar to'g'risida ma'lumot yo'q.")
        )
    elif role == "chilonzor":
        parts.append(_heading(section, "Ko'rib chiqish navbatidagi ishlar"))
        rows = [
            [f"№{row['submission'].pk}, {row['submission'].file_name}", str(row["submission"].assigned_to or "—"),
             row["waiting"], "muddati o'tgan" if row["overdue"] else "muddatida"]
            for row in context["waiting_rows"]
        ]
        parts.append(
            _table(["№", "APK ishi", "Kursant", "Kutish vaqti", "Holati"], _numbered(rows), [6, 36, 26, 15, 17],
                   ["center", "left", "left", "center", "center"])
            if rows else _p("Navbatda kutayotgan ish yo'q.")
        )
        decisions = context.get("recent_decisions") or []
        if decisions:
            parts.append(_p("So'nggi qabul qilingan qarorlar:", keep_next=True))
            parts.append(_table(
                ["№", "APK ishi", "Qaror", "Xodim", "Sana"],
                _numbered([
                    [f"№{item.pk}, {item.file_name}", str(item.status_label), str(item.reviewed_by or "—"),
                     f"{timezone.localtime(item.reviewed_at):%d.%m.%Y}"]
                    for item in decisions
                ]),
                [6, 34, 18, 26, 16], ["center", "left", "center", "left", "center"],
            ))
    else:
        parts.append(_heading(section, "Tuzatish uchun qaytarilgan ishlar"))
        rows = [
            [f"№{row.pk}, {row.file_name}", row.review_note or "—", f"{timezone.localtime(row.updated_at):%d.%m.%Y}"]
            for row in context["extra_rows"]
        ]
        parts.append(
            _table(["№", "APK ishi", "Qaytarish sababi", "Sana"], _numbered(rows), [6, 30, 48, 16], ["center", "left", "left", "center"])
            if rows else _p("Tuzatish uchun qaytarilgan ish yo'q.")
        )

    section += 1
    parts.append(_heading(section, "Aniqlangan topilmalar"))
    total_findings = context["finding_chart_total"]
    if total_findings:
        details = ", ".join(f"{row['label']} — {row['count']}" for row in context["finding_chart"])
        parts.append(_p(f"Tahlillar natijasida jami {_count(total_findings)} topilma kiritilgan: {details}."))
    else:
        parts.append(_p("Tahlillar natijasida topilma kiritilmagan."))
    repeated = [[group["label"], item["value"], item["count"]] for group in context["repeated_groups"] for item in group["items"]]
    if repeated:
        parts.append(_p("Bir nechta APK faylda takrorlangan qiymatlar:", keep_next=True))
        parts.append(_table(["№", "Turi", "Qiymat", "APK soni"], _numbered(repeated), [6, 24, 50, 20], ["center", "left", "left", "center"]))

    section += 1
    parts.append(_heading(section, "Xulosa"))
    for index, item in enumerate(_conclusions(context), start=1):
        parts.append(_p(f"{index}) {item}"))

    prepared_by = context.get("prepared_by") or ""
    parts.extend([
        _p("", indent=False, after=360),
        _p([_run("Tayyorladi:", bold=True), _run("\t"), _run(prepared_by or "____________________")],
           indent=False, tabs=[("right", TEXT_WIDTH)]),
        _p([_run(ROLE_UNITS.get(role, ""), italic=True, size=24), _run("\t"), _run("(imzo)", italic=True, size=20)],
           indent=False, tabs=[("right", TEXT_WIDTH)]),
        _p([_run(f"Hujjat tizimda {now:%d.%m.%Y} soat {now:%H:%M} da shakllantirildi.", italic=True, size=20)],
           indent=False, before=360),
    ])
    return "".join(parts)


def build_word_report(context):
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}" xmlns:r="{REL_NS}"><w:body>'
        f"{_report_body(context)}"
        '<w:sectPr><w:footerReference w:type="default" r:id="rId3"/>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="851" w:bottom="1134" w:left="1701" w:header="567" w:footer="567" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    styles_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{WORD_NS}">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}" w:eastAsia="{FONT}"/><w:sz w:val="{BODY_SIZE}"/><w:szCs w:val="{BODY_SIZE}"/><w:lang w:val="uz-Latn-UZ"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
</w:styles>'''
    footer_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{WORD_NS}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:t>1</w:t></w:r><w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
    document_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>'''

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", styles_xml)
        archive.writestr("word/footer1.xml", footer_xml)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
    return output.getvalue()
