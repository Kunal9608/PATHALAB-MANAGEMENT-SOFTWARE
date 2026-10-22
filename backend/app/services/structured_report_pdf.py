"""
Structured Report PDF Generator matching Akriti Diagnostics Center required layout.
Uses ReportLab to ensure pixel-perfect rendering across all platforms.
Designed for PRE-PRINTED A4 stationery.
"""
import io
import os
import html
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

def safe_p(val, style):
    """Safely escapes text before passing into ReportLab Paragraph to prevent XML parsing crashes & XSS."""
    if val is None:
        text = ""
    else:
        text = html.escape(str(val))
    return Paragraph(text, style)


class PushToBottom(Spacer):
    """
    A custom Spacer that pushes subsequent flowables to the bottom of the current frame.
    If the remaining space is less than required, it forces a page break so the content
    appears at the bottom of the next page.
    """
    def __init__(self, required_space_for_footer):
        Spacer.__init__(self, 1, 1)
        self.required_space = required_space_for_footer

    def wrap(self, aW, aH):
        availWidth, availHeight = aW, aH
        if availHeight < self.required_space:
            self.height = availHeight  # Force a page break
        else:
            self.height = availHeight - self.required_space
        return (availWidth, self.height)


def generate_structured_report_pdf(patient, booked_tests_data, verification_hash: str = "", letterhead_mode: bool = False) -> bytes:
    """
    Generate the official Akriti Diagnostics Center patient diagnostic report PDF
    designed exclusively for the pre-printed stationery.
    """
    buffer = io.BytesIO()
    
    # A4 = 595.27 x 841.89 points
    # topMargin 140 points clears physical pre-printed stationery header.
    # When letterhead_mode=True (e.g. WhatsApp digital delivery), topMargin is 30 points and digital header is added.
    top_margin = 30 if letterhead_mode else 140
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=top_margin,
        bottomMargin=100
    )

    styles = getSampleStyleSheet()

    secondary_color = colors.HexColor('#111111')   # Dark text
    border_color = colors.HexColor('#DDDDDD')      # Subtle border grey

    label_style = ParagraphStyle(
        'DemoLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#333333')
    )

    value_style = ParagraphStyle(
        'DemoValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#000000')
    )

    test_heading_style = ParagraphStyle(
        'TestHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceBefore=15,
        spaceAfter=10
    )

    th_style = ParagraphStyle(
        'TableHead',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.black
    )

    td_style = ParagraphStyle(
        'TableCellNormal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=secondary_color
    )

    td_bold_style = ParagraphStyle(
        'TableCellBold',
        parent=td_style,
        fontName='Helvetica-Bold'
    )

    end_of_report_style = ParagraphStyle(
        'EndOfReport',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceBefore=20,
        spaceAfter=10
    )

    signature_text_style = ParagraphStyle(
        'SignatureText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.black
    )

    signature_right_style = ParagraphStyle(
        'SignatureRight',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.black,
        alignment=TA_RIGHT
    )

    story = []

    # 0. Digital Pathology Letterhead Header (Included for WhatsApp digital delivery)
    if letterhead_mode:
        from backend.app.config import settings
        lab_name = getattr(settings, 'LAB_NAME', 'AKRITI DIAGNOSTICS CENTER') or 'AKRITI DIAGNOSTICS CENTER'
        lab_addr = getattr(settings, 'LAB_ADDRESS', '') or 'Main Road, Akriti Diagnostics Center'
        lab_phone = getattr(settings, 'LAB_PHONE', '') or '9006964947'

        lab_title_style = ParagraphStyle(
            'LabTitleHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#6D0001'),
            alignment=TA_CENTER
        )
        lab_sub_style = ParagraphStyle(
            'LabSubHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#222222'),
            alignment=TA_CENTER
        )
        lab_info_style = ParagraphStyle(
            'LabInfoLine',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=11,
            textColor=colors.HexColor('#555555'),
            alignment=TA_CENTER
        )

        story.append(Paragraph(lab_name.upper(), lab_title_style))
        story.append(Spacer(1, 2))
        story.append(Paragraph("ADVANCED CLINICAL PATHOLOGY & DIAGNOSTIC SERVICES", lab_sub_style))
        story.append(Spacer(1, 2))
        story.append(Paragraph(f"{lab_addr}   |   Contact: {lab_phone}", lab_info_style))
        story.append(Spacer(1, 2))
        story.append(Paragraph("Govt. Regd. Fully Computerized & Automated Testing Laboratory   |   Open All 7 Days", lab_info_style))
        story.append(Spacer(1, 6))

        # Distinct Brand Separator Line
        divider = Table([[""]], colWidths=[523], rowHeights=[1.5])
        divider.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#6D0001')),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(divider)
        story.append(Spacer(1, 8))

    # 1. Patient Demographics Block
    gender_str = patient.gender.value[0].upper() + patient.gender.value[1:] if hasattr(patient.gender, 'value') else str(patient.gender).capitalize()
    sample_date_str = patient.sample_date.strftime('%d-%b-%Y') if patient.sample_date else datetime.now().strftime('%d-%b-%Y')
    report_date_str = datetime.now().strftime('%d-%b-%Y')
    doctor_name = f"Dr. {patient.doctor.name}" if hasattr(patient, 'doctor') and patient.doctor else "SELF"
    
    # Ensuring Age / Gender are split into separate fields per specification
    demo_data = [
        [
            Paragraph("Name:", label_style),
            safe_p(patient.name.upper(), value_style),
            Paragraph("Patient ID:", label_style),
            safe_p(str(patient.patient_code), value_style)
        ],
        [
            Paragraph("Number:", label_style),
            safe_p(patient.mobile or "—", value_style),
            Paragraph("Gender:", label_style),
            safe_p(gender_str, value_style)
        ],
        [
            Paragraph("Age:", label_style),
            safe_p(f"{patient.age} Years", value_style),
            Paragraph("Referred By:", label_style),
            safe_p(doctor_name.upper(), value_style)
        ],
        [
            Paragraph("Collection Date:", label_style),
            safe_p(sample_date_str, value_style),
            Paragraph("Report Date:", label_style),
            safe_p(report_date_str, value_style)
        ]
    ]

    demo_table = Table(demo_data, colWidths=[90, 171, 95, 167])
    # pyrefly: ignore [bad-argument-type]
    demo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9F9F9')),
        ('BOX', (0, 0), (-1, -1), 0.5, border_color),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, border_color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(demo_table)
    story.append(Spacer(1, 10))

    # 2. Test Results Sections
    col_widths = [190, 110, 110, 113]  # Total 523pt

    for test_group in booked_tests_data:
        story.append(safe_p(f"** REPORT OF {test_group['test_name'].upper()} **", test_heading_style))

        table_rows = [
            [
                Paragraph("INVESTIGATION", th_style),
                Paragraph("RESULT", th_style),
                Paragraph("UNIT", th_style),
                Paragraph("REFERENCE RANGE", th_style)
            ]
        ]

        for p in test_group["parameters"]:
            val_str = p["value"]
            unit_str = p.get("unit") or ""
            ref_str = p.get("reference") or ""

            val_style_chosen = td_bold_style if p.get("is_abnormal") else td_style
            val_para = safe_p(val_str, val_style_chosen)

            table_rows.append([
                safe_p(p["name"], td_style),
                val_para,
                safe_p(unit_str, td_style),
                safe_p(ref_str, td_style)
            ])


        t = Table(table_rows, colWidths=col_widths, repeatRows=1)
        t_style = [
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, border_color),
            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]
        # pyrefly: ignore [bad-argument-type]
        t.setStyle(TableStyle(t_style))
        story.append(t)

    # 3. End of Report Marker
    story.append(Spacer(1, 15))
    story.append(Paragraph("**** END OF REPORT ****", end_of_report_style))

    # 4. Final Page Certification Block
    # The space required for the signature block is approximately 80 points.
    story.append(PushToBottom(required_space_for_footer=80))

    # Prepare signature image
    sig_path = os.path.join(os.path.dirname(__file__), "..", "assets", "dr_signature.png")
    sig_flowable = None
    if os.path.exists(sig_path):
        try:
            # The signature must not be huge or tiny. We preserve aspect ratio by setting a fixed height.
            from reportlab.lib.utils import ImageReader
            img_reader = ImageReader(sig_path)
            iw, ih = img_reader.getSize()
            target_height = 30
            target_width = (iw * target_height) / ih
            sig_flowable = Image(sig_path, width=target_width, height=target_height)
            sig_flowable.hAlign = 'CENTER'
        except Exception:
            sig_flowable = Spacer(1, 30)
    else:
        sig_flowable = Spacer(1, 30)

    # Styles for the names
    name_center_style = ParagraphStyle(
        'NameCenter',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.black,
        alignment=TA_CENTER
    )

    left_block = [
        Paragraph("Rajeev Ranjan", name_center_style),
        Paragraph("DMLT", name_center_style)
    ]

    right_block = [
        sig_flowable,
        Paragraph("Dr. M. K. Hansda", name_center_style),
        Paragraph("MBBS, CAS", name_center_style)
    ]

    cert_table = Table([[left_block, right_block]], colWidths=[261, 262])
    cert_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    
    story.append(cert_table)

    # Build PDF
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
