from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from PIL import Image as PillowImage
from PIL import ImageOps
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..models import ServiceOrder, ServiceOrderPhoto
from ..schemas import AiServiceReportDraft, GeneratedServiceReport, ReportPayload
from ..storage import StorageBackend

NAVY = colors.HexColor("#173B65")
ORANGE = colors.HexColor("#F28B2D")
GREEN = colors.HexColor("#23805A")
TEXT = colors.HexColor("#25364A")
MUTED = colors.HexColor("#68798D")
BORDER = colors.HexColor("#D9E1E8")
PALE_BLUE = colors.HexColor("#EEF4FA")
PALE_ORANGE = colors.HexColor("#FFF5E8")
WHITE = colors.white
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass
class MaterialLine:
    name: str
    quantity: str
    amount_cents: Optional[int]


@dataclass
class LaborLine:
    description: str
    hours: str
    amount_cents: Optional[int]


@dataclass
class ReportData:
    title: str
    summary: str = ""
    before_status: str = ""
    after_status: str = ""
    completed: list[str] = field(default_factory=list)
    materials: list[MaterialLine] = field(default_factory=list)
    labor: list[LaborLine] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    after_sales: list[str] = field(default_factory=list)
    customer_confirmation: str = ""
    needs_confirmation: list[str] = field(default_factory=list)


def _register_fonts() -> tuple[str, str]:
    regular_name = "GanwanleSans"
    bold_name = "GanwanleSansBold"
    if regular_name in pdfmetrics.getRegisteredFontNames():
        return regular_name, bold_name

    regular_candidates = [
        os.getenv("GANWANLE_PDF_FONT", ""),
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    bold_candidates = [
        os.getenv("GANWANLE_PDF_FONT_BOLD", ""),
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    regular_paths = [item for item in regular_candidates if item and Path(item).is_file()]
    bold_path = next((item for item in bold_candidates if item and Path(item).is_file()), None)
    for regular_path in regular_paths:
        try:
            regular_font = TTFont(regular_name, regular_path)
        except Exception:
            continue
        try:
            bold_font = TTFont(bold_name, bold_path or regular_path)
        except Exception:
            bold_font = TTFont(bold_name, regular_path)
        pdfmetrics.registerFont(regular_font)
        pdfmetrics.registerFont(bold_font)
        return regular_name, bold_name

    fallback_name = "STSong-Light"
    if fallback_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(fallback_name))
    return fallback_name, fallback_name


def _text(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    rendered = str(value).strip()
    return rendered or fallback


def _money(value: Optional[int]) -> str:
    return "待确认" if value is None else f"¥{value / 100:,.2f}"


def _date_time(value: Optional[datetime]) -> str:
    if value is None:
        return "--"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M")


def _mask_phone(phone: str) -> str:
    value = phone.strip()
    if len(value) >= 7:
        return f"{value[:3]}****{value[-4:]}"
    if len(value) >= 3:
        return f"{value[0]}***{value[-1]}"
    return value


def _service_address(order: ServiceOrder) -> str:
    lines = [order.service_address]
    if order.service_location_name and order.service_location_name not in order.service_address:
        lines.append(f"地点：{order.service_location_name}")
    if order.service_latitude is not None and order.service_longitude is not None:
        lines.append(f"定位：{order.service_latitude:.6f}, {order.service_longitude:.6f}")
    return "\n".join(lines)


def _report_data(order: ServiceOrder) -> ReportData:
    if not order.report_json:
        raise ValueError("service report is missing")

    try:
        report = AiServiceReportDraft.model_validate_json(order.report_json)
        return ReportData(
            title=_text(report.service_title, order.service_type),
            summary=_text(report.work_summary),
            before_status=_text(report.before_status),
            after_status=_text(report.after_status),
            completed=[item.content for item in report.completed_items],
            materials=[
                MaterialLine(
                    _text(item.name.value, "待确认材料"),
                    _text(item.quantity.value, "待确认"),
                    item.amount_cents.value,
                )
                for item in report.materials
            ],
            labor=[
                LaborLine(
                    _text(item.description.value, "服务费"),
                    _text(item.hours.value, "--"),
                    item.amount_cents.value,
                )
                for item in report.labor
            ],
            risks=report.risks,
            exceptions=report.exceptions,
            customer_confirmation=_text(report.customer_confirmation_text),
            needs_confirmation=report.needs_confirmation,
        )
    except ValueError:
        pass

    try:
        report = ReportPayload.model_validate_json(order.report_json)
        return ReportData(
            title=order.service_type,
            completed=report.completed_items,
            materials=[
                MaterialLine(item.name, item.quantity, item.amount_cents)
                for item in report.materials
            ],
            labor=[
                LaborLine(item.name, "--", item.amount_cents)
                for item in report.fee_items
            ],
            risks=report.risks,
            after_sales=[report.after_sales_reminder] if report.after_sales_reminder else [],
        )
    except ValueError:
        pass

    report = GeneratedServiceReport.model_validate_json(order.report_json)
    return ReportData(
        title=order.service_type,
        summary=report.summary,
        completed=[item.content for item in report.completed_items],
        materials=[
            MaterialLine(
                item.name,
                f"{item.quantity:g}{item.unit}" if item.quantity is not None else _text(item.unit, "待确认"),
                item.amount_cents,
            )
            for item in report.materials
        ],
        labor=[
            LaborLine(item.name, "--", item.amount_cents)
            for item in report.labor_items
        ],
        risks=[item.content for item in report.risks],
        after_sales=[item.content for item in report.after_sales],
        exceptions=report.warnings,
        needs_confirmation=report.missing_information,
    )


def _paragraph(value: object, style: ParagraphStyle, fallback: str = "--") -> Paragraph:
    rendered = _text(value, fallback)
    return Paragraph(escape(rendered).replace("\n", "<br/>"), style)


def _section_title(title: str, styles: dict[str, ParagraphStyle]) -> Table:
    return Table(
        [[_paragraph(title, styles["section"], "")]],
        colWidths=[180 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("LINEBEFORE", (0, 0), (0, -1), 3, ORANGE),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    )


def _bullet_rows(items: list[str], styles: dict[str, ParagraphStyle], empty: str) -> list:
    if not items:
        return [_paragraph(empty, styles["muted"])]
    return [
        Table(
            [[_paragraph(f"{index}.", styles["bullet"]), _paragraph(item, styles["body"])]],
            colWidths=[8 * mm, 172 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]),
        )
        for index, item in enumerate(items, start=1)
    ]


def _prepare_image(storage: StorageBackend, object_key: str, target: Path) -> Optional[tuple[Path, int, int]]:
    try:
        source = target.with_suffix(".source")
        storage.download_to(object_key, source)
        with PillowImage.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode in {"RGBA", "LA"}:
                background = PillowImage.new("RGB", image.size, "white")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((1800, 1400), PillowImage.Resampling.LANCZOS)
            image.save(target, "JPEG", quality=88, optimize=True)
            return target, image.width, image.height
    except Exception:
        return None


def _image_flowable(
    prepared: Optional[tuple[Path, int, int]],
    max_width: float,
    max_height: float,
    styles: dict[str, ParagraphStyle],
) -> object:
    if prepared is None:
        return Table(
            [[_paragraph("图片暂时无法读取", styles["image_placeholder"])]],
            colWidths=[max_width],
            rowHeights=[max_height],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F7F9")),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]),
        )
    path, width, height = prepared
    scale = min(max_width / width, max_height / height)
    return Image(str(path), width=width * scale, height=height * scale)


def _photo_cell(
    photo: ServiceOrderPhoto,
    prepared: Optional[tuple[Path, int, int]],
    styles: dict[str, ParagraphStyle],
) -> Table:
    return Table(
        [
            [_image_flowable(prepared, 83 * mm, 52 * mm, styles)],
            [_paragraph(photo.original_filename, styles["caption"], "现场照片")],
        ],
        colWidths=[85 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, 0), 3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F8FAFC")),
        ]),
    )


def _photo_grid(
    photos: list[ServiceOrderPhoto],
    prepared: dict[str, Optional[tuple[Path, int, int]]],
    styles: dict[str, ParagraphStyle],
) -> object:
    if not photos:
        return _paragraph("暂无照片", styles["muted"])
    cells = [_photo_cell(photo, prepared.get(photo.id), styles) for photo in photos]
    rows = [cells[index:index + 2] for index in range(0, len(cells), 2)]
    if len(rows[-1]) == 1:
        rows[-1].append("")
    return Table(
        rows,
        colWidths=[88 * mm, 88 * mm],
        hAlign="LEFT",
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]),
    )


def _styles(regular_font: str, bold_font: str) -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    base = ParagraphStyle(
        "GanwanleBody",
        parent=sample["BodyText"],
        fontName=regular_font,
        fontSize=9.5,
        leading=15,
        textColor=TEXT,
        wordWrap="CJK",
        spaceAfter=0,
    )
    return {
        "body": base,
        "small": ParagraphStyle("Small", parent=base, fontSize=8, leading=12),
        "muted": ParagraphStyle("Muted", parent=base, textColor=MUTED),
        "caption": ParagraphStyle("Caption", parent=base, fontSize=7.5, leading=11, textColor=MUTED, alignment=TA_CENTER),
        "title": ParagraphStyle("Title", parent=base, fontName=bold_font, fontSize=21, leading=27, textColor=WHITE, alignment=TA_LEFT),
        "company": ParagraphStyle("Company", parent=base, fontName=bold_font, fontSize=12, leading=16, textColor=WHITE),
        "header_meta": ParagraphStyle("HeaderMeta", parent=base, fontSize=8, leading=12, textColor=colors.HexColor("#DCE7F2"), alignment=TA_RIGHT),
        "section": ParagraphStyle("Section", parent=base, fontName=bold_font, fontSize=12.5, leading=17, textColor=NAVY),
        "label": ParagraphStyle("Label", parent=base, fontName=bold_font, fontSize=8.5, leading=13, textColor=MUTED),
        "table_header": ParagraphStyle("TableHeader", parent=base, fontName=bold_font, fontSize=8.5, leading=12, textColor=WHITE, alignment=TA_CENTER),
        "table_cell": ParagraphStyle("TableCell", parent=base, fontSize=8.5, leading=13),
        "table_money": ParagraphStyle("TableMoney", parent=base, fontSize=8.5, leading=13, alignment=TA_RIGHT),
        "bullet": ParagraphStyle("Bullet", parent=base, fontName=bold_font, textColor=GREEN, alignment=TA_CENTER),
        "total": ParagraphStyle("Total", parent=base, fontName=bold_font, fontSize=11, leading=15, textColor=NAVY),
        "total_money": ParagraphStyle("TotalMoney", parent=base, fontName=bold_font, fontSize=12, leading=16, textColor=NAVY, alignment=TA_RIGHT),
        "warning": ParagraphStyle("Warning", parent=base, textColor=colors.HexColor("#8B4C14")),
        "image_placeholder": ParagraphStyle("ImagePlaceholder", parent=base, fontSize=8, textColor=MUTED, alignment=TA_CENTER),
        "signature": ParagraphStyle("Signature", parent=base, fontName=bold_font, fontSize=10, leading=14, textColor=NAVY),
        "footer": ParagraphStyle("Footer", parent=base, fontSize=7.5, leading=10, textColor=MUTED, alignment=TA_CENTER),
    }


def _page_decorator(canvas, document, regular_font: str) -> None:
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, 12 * mm, A4[0] - 15 * mm, 12 * mm)
    canvas.setFont(regular_font, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(15 * mm, 7.5 * mm, "干完了 · 现场服务交付报告")
    canvas.drawRightString(A4[0] - 15 * mm, 7.5 * mm, f"第 {document.page} 页")
    canvas.restoreState()


def build_service_order_pdf(order: ServiceOrder, storage: StorageBackend) -> bytes:
    report = _report_data(order)
    regular_font, bold_font = _register_fonts()
    styles = _styles(regular_font, bold_font)
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=17 * mm,
        title=f"{order.order_no} 现场服务交付报告",
        author=order.company_name,
        subject=order.service_type,
    )
    story: list = []

    with TemporaryDirectory(prefix="ganwanle-pdf-") as temp_dir:
        temp_root = Path(temp_dir)
        all_photos = sorted(order.photos, key=lambda item: (item.phase, item.sort_order, item.created_at))
        prepared_photos = {
            photo.id: (
                _prepare_image(storage, photo.object_key, temp_root / f"photo-{photo.id}.jpg")
                if photo.object_key else None
            )
            for photo in all_photos
        }

        acceptance = order.customer_acceptance
        prepared_signature = (
            _prepare_image(storage, acceptance.signature_object_key, temp_root / "signature.jpg")
            if acceptance else None
        )

        status_text = "已完成验收" if order.status == "accepted" else "等待客户验收"
        header = Table(
            [
                [
                    [
                        _paragraph(order.company_name, styles["company"]),
                        Spacer(1, 3),
                        _paragraph("现场服务交付报告", styles["title"]),
                    ],
                    _paragraph(
                        f"{status_text}\n服务单号：{order.order_no}",
                        styles["header_meta"],
                    ),
                ]
            ],
            colWidths=[125 * mm, 55 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 13),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
            ]),
        )
        story.extend([header, Spacer(1, 7 * mm)])

        info_rows = [
            [
                _paragraph("服务项目", styles["label"]),
                _paragraph(report.title, styles["body"]),
                _paragraph("服务师傅", styles["label"]),
                _paragraph(order.technician_name, styles["body"]),
            ],
            [
                _paragraph("客户姓名", styles["label"]),
                _paragraph(order.customer_name, styles["body"]),
                _paragraph("联系电话", styles["label"]),
                _paragraph(_mask_phone(order.customer_phone), styles["body"]),
            ],
            [
                _paragraph("服务地址", styles["label"]),
                _paragraph(_service_address(order), styles["body"]),
                _paragraph("创建时间", styles["label"]),
                _paragraph(_date_time(order.created_at), styles["body"]),
            ],
            [
                _paragraph("验收状态", styles["label"]),
                _paragraph(status_text, styles["body"]),
                _paragraph("验收时间", styles["label"]),
                _paragraph(_date_time(acceptance.accepted_at if acceptance else None), styles["body"]),
            ],
        ]
        info = Table(
            info_rows,
            colWidths=[21 * mm, 69 * mm, 21 * mm, 69 * mm],
            style=TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F7F9FB")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F7F9FB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        )
        story.extend([info, Spacer(1, 6 * mm)])

        summary_parts = [
            ("服务摘要", report.summary),
            ("施工前状态", report.before_status),
            ("施工后状态", report.after_status),
        ]
        available_summary = [(label, value) for label, value in summary_parts if value]
        if available_summary:
            story.extend([_section_title("服务概况", styles), Spacer(1, 2 * mm)])
            summary_rows = [
                [_paragraph(label, styles["label"]), _paragraph(value, styles["body"])]
                for label, value in available_summary
            ]
            story.extend([
                Table(
                    summary_rows,
                    colWidths=[28 * mm, 152 * mm],
                    style=TableStyle([
                        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F7F9FB")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]),
                ),
                Spacer(1, 6 * mm),
            ])

        story.extend([_section_title("完成内容", styles), Spacer(1, 2 * mm)])
        story.extend(_bullet_rows(report.completed, styles, "暂无完成内容记录"))
        story.append(Spacer(1, 5 * mm))

        before_photos = [item for item in all_photos if item.phase == "before"]
        after_photos = [item for item in all_photos if item.phase == "after"]
        story.extend([
            KeepTogether([
                _section_title("施工前照片", styles),
                Spacer(1, 2 * mm),
                _photo_grid(before_photos, prepared_photos, styles),
            ]),
            Spacer(1, 5 * mm),
            KeepTogether([
                _section_title("施工后照片", styles),
                Spacer(1, 2 * mm),
                _photo_grid(after_photos, prepared_photos, styles),
            ]),
            Spacer(1, 5 * mm),
        ])

        story.extend([_section_title("材料与费用", styles), Spacer(1, 2 * mm)])
        material_rows = [
            [
                _paragraph("材料名称", styles["table_header"]),
                _paragraph("数量/规格", styles["table_header"]),
                _paragraph("金额", styles["table_header"]),
            ]
        ]
        material_rows.extend([
            [
                _paragraph(item.name, styles["table_cell"]),
                _paragraph(item.quantity, styles["table_cell"]),
                _paragraph(_money(item.amount_cents), styles["table_money"]),
            ]
            for item in report.materials
        ])
        if not report.materials:
            material_rows.append([
                _paragraph("本次服务未记录材料", styles["muted"]),
                "",
                _paragraph("¥0.00", styles["table_money"]),
            ])
        material_table = LongTable(
            material_rows,
            colWidths=[88 * mm, 52 * mm, 40 * mm],
            repeatRows=1,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("SPAN", (0, 1), (1, 1)) if not report.materials else ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        )
        story.extend([material_table, Spacer(1, 3 * mm)])

        if report.labor:
            labor_rows = [[
                _paragraph("服务/工时", styles["table_header"]),
                _paragraph("时长", styles["table_header"]),
                _paragraph("金额", styles["table_header"]),
            ]]
            labor_rows.extend([
                [
                    _paragraph(item.description, styles["table_cell"]),
                    _paragraph(item.hours, styles["table_cell"]),
                    _paragraph(_money(item.amount_cents), styles["table_money"]),
                ]
                for item in report.labor
            ])
            story.extend([
                LongTable(
                    labor_rows,
                    colWidths=[88 * mm, 52 * mm, 40 * mm],
                    repeatRows=1,
                    style=TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]),
                ),
                Spacer(1, 3 * mm),
            ])

        line_total = sum(item.amount_cents or 0 for item in report.materials)
        line_total += sum(item.amount_cents or 0 for item in report.labor)
        total_amount = order.total_amount_cents or line_total
        due_amount = max(0, total_amount - order.paid_amount_cents)
        total_table = Table(
            [
                [
                    _paragraph("合计", styles["total"]),
                    _paragraph(_money(total_amount), styles["total_money"]),
                    _paragraph("已收", styles["total"]),
                    _paragraph(_money(order.paid_amount_cents), styles["total_money"]),
                    _paragraph("待收", styles["total"]),
                    _paragraph(_money(due_amount), styles["total_money"]),
                ]
            ],
            colWidths=[20 * mm, 40 * mm, 20 * mm, 40 * mm, 20 * mm, 40 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), PALE_ORANGE),
                ("BOX", (0, 0), (-1, -1), 0.8, ORANGE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]),
        )
        story.extend([total_table, Spacer(1, 6 * mm)])

        risk_items = [*report.risks, *report.exceptions]
        story.extend([_section_title("风险、异常与售后说明", styles), Spacer(1, 2 * mm)])
        if risk_items:
            for item in risk_items:
                story.append(_paragraph(f"• {item}", styles["warning"]))
                story.append(Spacer(1, 1.5 * mm))
        else:
            story.append(_paragraph("本次服务未记录风险或异常。", styles["muted"]))
        for item in report.after_sales:
            story.extend([Spacer(1, 1 * mm), _paragraph(f"售后提醒：{item}", styles["body"])])
        if report.customer_confirmation:
            story.extend([Spacer(1, 1 * mm), _paragraph(f"客户确认：{report.customer_confirmation}", styles["body"])])
        if report.needs_confirmation:
            story.extend([
                Spacer(1, 2 * mm),
                _paragraph("以下信息仍需确认：" + "；".join(report.needs_confirmation), styles["warning"]),
            ])
        story.append(Spacer(1, 6 * mm))

        signature_image = _image_flowable(prepared_signature, 90 * mm, 34 * mm, styles)
        signature_rows = [
            [
                [
                    _paragraph("客户签名", styles["signature"]),
                    Spacer(1, 2 * mm),
                    signature_image if acceptance else _paragraph("等待客户签字验收", styles["muted"]),
                ],
                [
                    _paragraph("验收结果", styles["signature"]),
                    Spacer(1, 3 * mm),
                    _paragraph(status_text, styles["body"]),
                    Spacer(1, 2 * mm),
                    _paragraph(f"确认时间：{_date_time(acceptance.accepted_at if acceptance else None)}", styles["small"]),
                ],
            ]
        ]
        story.extend([
            _section_title("客户验收", styles),
            Spacer(1, 2 * mm),
            KeepTogether(Table(
                signature_rows,
                colWidths=[110 * mm, 70 * mm],
                style=TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                    ("LINEBEFORE", (1, 0), (1, -1), 0.6, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]),
            )),
            Spacer(1, 5 * mm),
            _paragraph(
                f"报告生成时间：{_date_time(datetime.now(timezone.utc))}。本报告由服务单现场记录自动生成。",
                styles["footer"],
            ),
        ])

        document.build(
            story,
            onFirstPage=lambda canvas, doc: _page_decorator(canvas, doc, regular_font),
            onLaterPages=lambda canvas, doc: _page_decorator(canvas, doc, regular_font),
        )

    return output.getvalue()
