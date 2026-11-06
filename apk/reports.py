"""Build a lightweight, dependency-free DOCX dashboard report."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape

from django.utils import timezone


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


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


def _paragraph(value, style=None, color=None, bold=False, size=None, after=100):
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    spacing = f'<w:spacing w:after="{after}"/>'
    properties = []
    if bold:
        properties.append("<w:b/>")
    if color:
        properties.append(f'<w:color w:val="{color}"/>')
    if size:
        properties.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    run_properties = f"<w:rPr>{''.join(properties)}</w:rPr>" if properties else ""
    return (
        f"<w:p><w:pPr>{style_xml}{spacing}</w:pPr><w:r>{run_properties}"
        f'<w:t xml:space="preserve">{_text(value)}</w:t></w:r></w:p>'
    )


def _cell(value, width, header=False, alternate=False):
    fill = "1E3A5F" if header else ("F2F5F9" if alternate else "FFFFFF")
    color = "FFFFFF" if header else "172235"
    bold = "<w:b/>" if header else ""
    size = "20" if header else "19"
    text = _text(value)
    return (
        "<w:tc><w:tcPr>"
        f'<w:tcW w:w="{width}" w:type="dxa"/><w:shd w:fill="{fill}" w:val="clear"/>'
        '<w:vAlign w:val="center"/></w:tcPr>'
        f"<w:p><w:pPr><w:spacing w:before=\"35\" w:after=\"35\"/></w:pPr><w:r><w:rPr>"
        f'<w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:color w:val="{color}"/>'
        f"{bold}<w:sz w:val=\"{size}\"/></w:rPr><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p></w:tc>"
    )


def _table(headers, rows):
    headers = list(headers)
    rows = list(rows)
    column_count = max(len(headers), 1)
    widths = [9360 // column_count] * column_count
    widths[-1] += 9360 - sum(widths)
    borders = (
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:color="DCE3EC"/>'
        '<w:left w:val="single" w:sz="4" w:color="DCE3EC"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="DCE3EC"/>'
        '<w:right w:val="single" w:sz="4" w:color="DCE3EC"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="DCE3EC"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="DCE3EC"/>'
        "</w:tblBorders>"
    )
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    xml = (
        '<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/>'
        f"{borders}<w:tblLayout w:type=\"fixed\"/>"
        '<w:tblCellMar><w:top w:w="85" w:type="dxa"/><w:left w:w="110" w:type="dxa"/>'
        '<w:bottom w:w="85" w:type="dxa"/><w:right w:w="110" w:type="dxa"/></w:tblCellMar>'
        f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>"
    )
    all_rows = [headers] + rows
    for row_index, row in enumerate(all_rows):
        row = list(row)[:column_count]
        row.extend([""] * (column_count - len(row)))
        xml += "<w:tr>"
        for index, value in enumerate(row):
            xml += _cell(value, widths[index], header=row_index == 0, alternate=row_index % 2 == 0)
        xml += "</w:tr>"
    return xml + "</w:tbl>"


def _bar(percent, width=22):
    count = max(0, min(width, round(float(percent or 0) * width / 100)))
    return ("■" * count) + ("·" * (width - count))


def _report_body(context):
    now = timezone.localtime()
    role = context["role"]
    role_labels = {
        "admin": "Admin",
        "mvd": "MVD",
        "chilonzor": "Chilonzor",
        "kursant": "Kursant",
    }
    parts = [
        _paragraph("RAQAMLI QALQON  /  APK TAHLIL", style="Subtitle", color="1E3A5F", bold=True, size=18, after=60),
        _paragraph(f"{context['role_title']} — tahliliy hisobot", style="Title", after=100),
        _paragraph(f"Rol: {role_labels.get(role, role)}", color="5A6478", after=40),
        _paragraph(
            f"Tanlangan davr: {context['period_start']:%d.%m.%Y} – {context['period_end']:%d.%m.%Y} ({context['period_days']} kun)",
            color="5A6478",
            after=40,
        ),
        _paragraph(f"Tayyorlangan vaqt: {now:%d.%m.%Y %H:%M}", color="5A6478", after=220),
        _paragraph("Asosiy ko'rsatkichlar", style="Heading1"),
        _table(
            ["Ko'rsatkich", "Qiymat", "Izoh"],
            [[item["label"], item["value"], item["hint"]] for item in context["kpis"]],
        ),
        _paragraph("Holatlar va ulushi", style="Heading1", after=80),
        _table(
            ["Holat", "Soni", "Ulushi", "Diagramma"],
            [
                [row["label"], row["count"], f'{row["share"]}%', _bar(row["share"])]
                for row in context["chart_rows"]
            ] or [["Ma'lumot yo'q", 0, "0%", _bar(0)]],
        ),
        _paragraph(context["trend_title"], style="Heading1", after=80),
        _table(
            ["Sana", "Soni", "Ustunli ko'rsatkich"],
            [
                [item["day"].strftime("%d.%m.%Y"), item["count"], _bar(item["height"])]
                for item in context["daily"]
            ],
        ),
    ]

    if role == "admin":
        parts.extend(
            [
                _paragraph("Kursantlar faoliyati", style="Heading1"),
                _table(
                    ["Kursant", "Faol ishlar", "Qabul qilingan", "Qaytarilgan"],
                    [[row["name"], row["active"], row["accepted"], row["returned"]] for row in context["performance_rows"]]
                    or [["Ma'lumot yo'q", 0, 0, 0]],
                ),
            ]
        )
    elif role == "mvd":
        parts.extend(
            [
                _paragraph("APK yuborgan manbalar", style="Heading1"),
                _table(["Manba", "APK soni"], [[row["name"], row["count"]] for row in context["source_rows"]] or [["Ma'lumot yo'q", 0]]),
            ]
        )
    elif role == "chilonzor":
        parts.extend(
            [
                _paragraph("Ko'rib chiqish navbati", style="Heading1"),
                _table(
                    ["APK ishi", "Kursant", "Kutgan vaqt", "Holat"],
                    [
                        [
                            f'#{row["submission"].pk} {row["submission"].file_name}',
                            str(row["submission"].assigned_to or "—"),
                            row["waiting"],
                            "Kechikkan" if row["overdue"] else "Kutilmoqda",
                        ]
                        for row in context["waiting_rows"]
                    ]
                    or [["Navbat bo'sh", "—", "—", "—"]],
                ),
            ]
        )
    else:
        parts.extend(
            [
                _paragraph("Qaytarilgan ishlar va izohlar", style="Heading1"),
                _table(
                    ["APK ishi", "Qaytarish sababi", "Yangilangan"],
                    [
                        [f'#{row.pk} {row.file_name}', row.review_note or "—", timezone.localtime(row.updated_at).strftime("%d.%m.%Y %H:%M")]
                        for row in context["extra_rows"]
                    ]
                    or [["Qaytarilgan ish yo'q", "—", "—"]],
                ),
            ]
        )

    parts.append(_paragraph("Topilmalar tarkibi", style="Heading1"))
    parts.append(
        _table(
            ["Topilma turi", "Soni", "Ulushi", "Diagramma"],
            [
                [row["label"], row["count"], f'{row["share"]}%', _bar(row["share"])]
                for row in context["finding_chart"]
            ]
            or [["Topilmalar yo'q", 0, "0%", _bar(0)]],
        )
    )

    repeated = [
        [group["label"], item["value"], item["count"]]
        for group in context["repeated_groups"]
        for item in group["items"]
    ]
    parts.extend(
        [
            _paragraph("Takrorlangan topilmalar", style="Heading1"),
            _table(["Turi", "Qiymat", "Uchrangan APK"], repeated or [["Takror yo'q", "—", 0]]),
            _paragraph("So'nggi harakatlar", style="Heading1"),
            _table(
                ["Vaqt", "APK", "Harakat", "Foydalanuvchi"],
                [
                    [
                        timezone.localtime(event.created_at).strftime("%d.%m.%Y %H:%M"),
                        f"#{event.submission_id}",
                        str(event.action_label),
                        str(event.actor or "Tizim"),
                    ]
                    for event in context["recent_events"]
                ]
                or [["—", "—", "Harakat yo'q", "—"]],
            ),
        ]
    )
    return "".join(parts)


def build_word_report(context):
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}" xmlns:r="{REL_NS}"><w:body>'
        f"{_report_body(context)}"
        '<w:sectPr><w:headerReference w:type="default" r:id="rId2"/>'
        '<w:footerReference w:type="default" r:id="rId3"/>'
        '<w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="1440" '
        'w:bottom="1080" w:left="1440" w:header="540" w:footer="540" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    styles_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{WORD_NS}">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:sz w:val="20"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:rFonts w:ascii="Aptos Display" w:hAnsi="Aptos Display"/><w:color w:val="172235"/><w:b/><w:sz w:val="34"/></w:rPr><w:pPr><w:spacing w:after="140"/><w:keepNext/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:color w:val="1E3A5F"/><w:sz w:val="18"/></w:rPr><w:pPr><w:spacing w:after="60"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:rPr><w:rFonts w:ascii="Aptos Display" w:hAnsi="Aptos Display"/><w:color w:val="1E3A5F"/><w:b/><w:sz w:val="25"/></w:rPr><w:pPr><w:spacing w:before="280" w:after="100"/><w:keepNext/></w:pPr></w:style>
</w:styles>'''
    header_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="{WORD_NS}"><w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="8" w:space="5" w:color="DCE3EC"/></w:pBdr></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:color w:val="5A6478"/><w:sz w:val="16"/></w:rPr><w:t>RAQAMLI QALQON  /  APK TAHLIL</w:t></w:r></w:p></w:hdr>'''
    footer_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{WORD_NS}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:color w:val="7A8495"/><w:sz w:val="16"/></w:rPr><w:t>Ichki hisobot  •  Raqamli Qalqon</w:t></w:r></w:p></w:ftr>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
    document_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>'''

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", styles_xml)
        archive.writestr("word/header1.xml", header_xml)
        archive.writestr("word/footer1.xml", footer_xml)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
    return output.getvalue()
