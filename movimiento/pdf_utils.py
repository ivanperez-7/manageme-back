import os
import logging

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import Table, TableStyle
from reportlab.platypus.paragraph import Paragraph

logger = logging.getLogger(__name__)

HALF_LETTER_LANDSCAPE = (8.5 * inch, 5.5 * inch)

ML = 0.5 * inch
MR = 0.5 * inch
MT = 14
MB = 18

PW, PH = HALF_LETTER_LANDSCAPE
CW = PW - ML - MR

FOLIO_W = 144
FOLIO_H = 80
FOLIO_X = PW - MR - FOLIO_W
FOLIO_TOP = PH - MT
FOLIO_HEADER_H = 20

TITLE_BAR_H = 22
TITLE_TOP = FOLIO_TOP - FOLIO_H - 4
TITLE_BOTTOM = TITLE_TOP - TITLE_BAR_H

CI_TOP = TITLE_BOTTOM - 8
CI_ROW_H = 18
CI_GAP = 4

TABLE_TOP = CI_TOP - 3 * (CI_ROW_H + CI_GAP) - 6
TABLE_BOTTOM = 50
TABLE_HEADER_H = 18

FOOTER_Y = 38


def _resolve_logo(data):
    path = data.get('logo_path') or ''
    if not path:
        path = settings.BASE_DIR / 'static' / 'img' / 'logo.png'
    elif not os.path.isabs(path):
        path = settings.BASE_DIR / path
    return str(path)


def _draw_header(c, data):
    logo_path = _resolve_logo(data)
    if os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, ML, FOLIO_TOP - 45, width=85, height=45, preserveAspectRatio=True)
        except Exception:
            logger.warning('Cannot draw logo: %s', logo_path)

    cx = PW / 2
    c.setFont('Helvetica-Bold', 13)
    c.drawCentredString(cx, FOLIO_TOP - 6, 'FRANCISCO JAVIER PEREZ RIVERO')

    c.setFont('Helvetica', 8)
    c.drawCentredString(cx, FOLIO_TOP - 22, 'VENTA, RENTA, SERVICIO Y CONSUMIBLES PARA')
    c.drawCentredString(cx, FOLIO_TOP - 34, 'MULTIFUNCIONALES DIGITALES')
    c.drawCentredString(cx, FOLIO_TOP - 44, 'DE ALTA PRODUCCIÓN')

    c.setFont('Helvetica', 6.5)
    c.drawCentredString(cx, FOLIO_TOP - 56,
        'Av. 50 No. 247 x 47 y 49-C Francisco de Montejo / Tel: 195 07 83 Cel: 9994 04 92 18')

    _draw_folio_box(c, data)


def _draw_folio_box(c, data):
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)

    num_top = FOLIO_TOP - FOLIO_HEADER_H
    num_bottom = FOLIO_TOP - FOLIO_H

    c.setFillColor(colors.black)
    c.rect(FOLIO_X, num_top, FOLIO_W, FOLIO_HEADER_H, stroke=1, fill=1)

    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(FOLIO_X + FOLIO_W / 2, num_top + 5, 'Folio')

    c.setFillColor(colors.white)
    c.rect(FOLIO_X, num_bottom, FOLIO_W, num_top - num_bottom, stroke=1, fill=0)

    c.setFillColor(colors.black)
    c.setFont('Helvetica-Bold', 16)
    c.drawCentredString(FOLIO_X + FOLIO_W / 2, num_bottom + (num_top - num_bottom) / 2 - 6,
                        data.get('folio', ''))


def _draw_title(c, data):
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)
    c.rect(ML, TITLE_BOTTOM, CW, TITLE_BAR_H, stroke=1, fill=1)

    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(PW / 2, TITLE_BOTTOM + 5, 'Salida de Almacén')


def _draw_customer_info(c, data):
    y = CI_TOP

    c.setFillColor(colors.black)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML, y, 'Razon Social:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 70, y, data.get('razon_social', ''))
    c.setLineWidth(0.5)
    c.line(ML + 70, y - 2, ML + 400, y - 2)

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 410, y, 'Fecha:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 445, y, data.get('fecha', ''))
    c.line(ML + 445, y - 2, ML + CW, y - 2)

    y -= CI_ROW_H + CI_GAP

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML, y, 'Contador color:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 78, y, data.get('contador_color', ''))
    c.line(ML + 78, y - 2, ML + 250, y - 2)

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 270, y, 'Contador b/n:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 345, y, data.get('contador_bn', ''))
    c.line(ML + 345, y - 2, ML + CW, y - 2)

    y -= CI_ROW_H + CI_GAP

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML, y, 'Marca:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 38, y, data.get('marca', ''))
    c.line(ML + 38, y - 2, ML + 170, y - 2)

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 185, y, 'Modelo:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 228, y, data.get('modelo', ''))
    c.line(ML + 228, y - 2, ML + 370, y - 2)

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 385, y, 'Serie:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 418, y, data.get('serie', ''))
    c.line(ML + 418, y - 2, ML + CW, y - 2)


def _draw_items_table(c, data):
    items = data.get('items', [])

    body_style = ParagraphStyle('body', fontSize=8, leading=10, fontName='Helvetica')
    center_style = ParagraphStyle('center', fontSize=8, leading=10, fontName='Helvetica',
                                  alignment=TA_CENTER)
    right_style = ParagraphStyle('right', fontSize=8, leading=10, fontName='Helvetica',
                                 alignment=TA_RIGHT)
    header_style = ParagraphStyle('header', fontSize=8, leading=10, fontName='Helvetica-Bold',
                                  textColor=colors.white, alignment=TA_CENTER)
    empty_style = ParagraphStyle('empty', fontSize=8, leading=10, fontName='Helvetica')

    header = [
        Paragraph('Cantidad', header_style),
        Paragraph('Descripcion', header_style),
        Paragraph('Codigo', header_style),
        Paragraph('Costo', header_style),
    ]
    table_body = [header]

    num_rows = max(len(items), 7)
    for i in range(num_rows):
        if i < len(items):
            table_body.append([
                Paragraph(str(items[i]['cantidad']), center_style),
                Paragraph(items[i]['descripcion'], body_style),
                Paragraph(items[i]['codigo'], center_style),
                Paragraph(items[i].get('costo', ''), right_style),
            ])
        else:
            table_body.append([
                Paragraph('&nbsp;', empty_style),
                Paragraph('&nbsp;', empty_style),
                Paragraph('&nbsp;', empty_style),
                Paragraph('&nbsp;', empty_style),
            ])

    col_widths = [CW * 0.15, CW * 0.55, CW * 0.15, CW * 0.15]

    available_h = TABLE_TOP - TABLE_BOTTOM
    data_h = max(18, (available_h - TABLE_HEADER_H) / num_rows)
    row_heights = [TABLE_HEADER_H] + [data_h] * num_rows

    t = Table(table_body, colWidths=col_widths, rowHeights=row_heights)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))

    t.wrapOn(c, CW, available_h)
    t.drawOn(c, ML, TABLE_BOTTOM)


def _draw_footer(c, data):
    c.setFillColor(colors.black)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML, FOOTER_Y, 'Nombre y Firma:')

    c.setFont('Helvetica', 8)
    c.drawString(ML + 75, FOOTER_Y, data.get('nombre_firma', ''))

    c.setLineWidth(0.5)
    c.line(ML + 75, FOOTER_Y - 2, ML + CW, FOOTER_Y - 2)


def generar_pdf_salida(buf, data):
    c = canvas_module.Canvas(buf, pagesize=HALF_LETTER_LANDSCAPE)
    _draw_header(c, data)
    _draw_title(c, data)
    _draw_customer_info(c, data)
    _draw_items_table(c, data)
    _draw_footer(c, data)
    c.showPage()
    c.save()
