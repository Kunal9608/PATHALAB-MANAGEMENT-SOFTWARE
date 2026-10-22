import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_patients_pdf(patients) -> bytes:
    buffer = io.BytesIO()
    # Margins: 0.5 inch (36 points)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#6D0001'), # Red header
        alignment=1, # Center
        spaceAfter=10
    )
    
    subtitle_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#555555'),
        alignment=1,
        spaceAfter=20
    )
    
    header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white
    )
    
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#111111')
    )
    
    cell_bold_style = ParagraphStyle(
        'TableCellBold',
        parent=cell_style,
        fontName='Helvetica-Bold'
    )

    story = []
    
    # Header
    story.append(Paragraph("AKRITI DIAGNOSTICS CENTER", title_style))
    story.append(Paragraph(
        f"Patient Records Backup (Past 15 Days) — Generated on {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}<br/>"
        f"Total Records: {len(patients)}",
        subtitle_style
    ))
    
    # Table data
    # Headers
    data = [[
        Paragraph("Date", header_style),
        Paragraph("Patient ID", header_style),
        Paragraph("Name", header_style),
        Paragraph("Age/Sex", header_style),
        Paragraph("Mobile", header_style),
        Paragraph("Tests", header_style),
        Paragraph("Billing (Tot/Pd/Due)", header_style)
    ]]
    
    for p in patients:
        # Format tests
        test_names = ", ".join([pt.test.name for pt in p.patient_tests if pt.test])
        
        # Format billing
        disc = float(p.discount_amount or 0)
        total = float(p.total_amount or 0)
        net = max(0.0, total - disc)
        paid = float(p.amount_paid or 0)
        due = max(0.0, net - paid)
        billing_text = f"Tot: {total:.0f}\nPaid: {paid:.0f}\nDue: {due:.0f}"
        if disc > 0:
            billing_text = f"Net: {net:.0f}\n" + billing_text
            
        import html
        data.append([
            Paragraph(p.created_at.strftime('%d-%b-%Y') if p.created_at else "—", cell_style),
            Paragraph(html.escape(str(p.patient_code)), cell_bold_style),
            Paragraph(html.escape(str(p.name)), cell_bold_style),
            Paragraph(html.escape(f"{p.age} y / {p.gender.value[0].upper() if hasattr(p.gender, 'value') else str(p.gender)[0].upper() if p.gender else '—'}"), cell_style),
            Paragraph(html.escape(str(p.mobile or "—")), cell_style),
            Paragraph(html.escape(str(test_names or "—")), cell_style),
            Paragraph(html.escape(billing_text).replace("\n", "<br/>"), cell_style)
        ])

        
    # Table column widths (Total = 523pt)
    col_widths = [65, 70, 90, 50, 65, 100, 83]
    
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#6D0001')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E0E0E0')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F9F9F9')]),
        ('BOTTOMPADDING', (0,1), (-1,-1), 6),
        ('TOPPADDING', (0,1), (-1,-1), 6),
    ]))
    
    story.append(t)
    
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
