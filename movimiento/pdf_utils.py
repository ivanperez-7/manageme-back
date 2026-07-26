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
FOLIO_H = 60
FOLIO_X = PW - MR - FOLIO_W
FOLIO_TOP = PH - MT
FOLIO_HEADER_H = 20
FOLIO_BOTTOM = FOLIO_TOP - FOLIO_H

CI_TITLE_TOP = FOLIO_BOTTOM - 18
CI_TITLE_H = 22
CI_TOP = CI_TITLE_TOP - CI_TITLE_H
CI_ROW_H = 20
CI_BOTTOM = CI_TOP - 3 * CI_ROW_H

TABLE_TOP = CI_BOTTOM - 4
TABLE_BOTTOM = 50
TABLE_HEADER_H = 18

FOOTER_Y = 28


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
            c.drawImage(logo_path, ML, FOLIO_TOP - FOLIO_H, width=120, height=FOLIO_H,
                        preserveAspectRatio=True)
        except Exception:
            logger.warning('Cannot draw logo: %s', logo_path)

    cx = PW / 2

    c.setFont('Helvetica-Oblique', 13)
    name = 'FRANCISCO JAVIER PEREZ RIVERO'
    nw = c.stringWidth(name, 'Helvetica-Oblique', 13)
    c.drawCentredString(cx, FOLIO_TOP - 12, name)
    c.setLineWidth(0.5)
    c.line(cx - nw / 2, FOLIO_TOP - 16, cx + nw / 2, FOLIO_TOP - 16)

    c.setFont('Helvetica-Oblique', 8)
    c.drawCentredString(cx, FOLIO_TOP - 28, 'VENTA, RENTA, SERVICIO Y CONSUMIBLES PARA')
    c.drawCentredString(cx, FOLIO_TOP - 40, 'MULTIFUNCIONALES DIGITALES')
    c.drawCentredString(cx, FOLIO_TOP - 50, 'DE ALTA PRODUCCIÓN')

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.setFont('Helvetica-Bold', 11)
    c.drawCentredString(cx, FOLIO_BOTTOM - 14,
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
    c.rect(FOLIO_X, num_bottom, FOLIO_W, num_top - num_bottom, stroke=1, fill=1)

    c.setFillColor(colors.black)
    c.setFont('Helvetica-Bold', 16)
    c.drawCentredString(FOLIO_X + FOLIO_W / 2, num_bottom + (num_top - num_bottom) / 2 - 6,
                        data.get('folio', ''))


def _draw_customer_table(c, data):
    y1 = CI_TOP
    y2 = y1 - CI_ROW_H
    y3 = y2 - CI_ROW_H
    y4 = y3 - CI_ROW_H

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)

    table_h = CI_TITLE_H + CI_TOP - y4

    c.rect(ML, y4, CW, table_h, stroke=1, fill=0)

    c.setFillColor(colors.black)
    c.rect(ML, y1, CW, CI_TITLE_H, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(PW / 2, y1 + 7, 'Salida de Almacén')

    c.setStrokeColor(colors.black)
    c.setFillColor(colors.black)
    c.line(ML, y2, ML + CW, y2)
    c.line(ML, y3, ML + CW, y3)

    fecha_x = ML + 370
    c.line(fecha_x, y1, fecha_x, y2)

    marca_end = ML + 110
    modelo_end = ML + 310
    c.line(marca_end, y3, marca_end, y4)
    c.line(modelo_end, y3, modelo_end, y4)

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 6, y1 - 14, 'Razon Social:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 74, y1 - 14, data.get('razon_social', ''))

    c.setFont('Helvetica-Bold', 8)
    c.drawString(fecha_x + 6, y1 - 14, 'Fecha:')
    c.setFont('Helvetica', 8)
    c.drawString(fecha_x + 40, y1 - 14, data.get('fecha', ''))

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 6, y2 - 14, 'Contador de uso:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 88, y2 - 14, data.get('contador_uso', ''))

    c.setFont('Helvetica-Bold', 8)
    c.drawString(ML + 6, y3 - 14, 'Marca:')
    c.setFont('Helvetica', 8)
    c.drawString(ML + 44, y3 - 14, data.get('marca', ''))

    c.setFont('Helvetica-Bold', 8)
    c.drawString(marca_end + 6, y3 - 14, 'Modelo:')
    c.setFont('Helvetica', 8)
    c.drawString(marca_end + 46, y3 - 14, data.get('modelo', ''))

    c.setFont('Helvetica-Bold', 8)
    c.drawString(modelo_end + 6, y3 - 14, 'Serie:')
    c.setFont('Helvetica', 8)
    c.drawString(modelo_end + 38, y3 - 14, data.get('serie', ''))


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
    _draw_customer_table(c, data)
    _draw_items_table(c, data)
    _draw_footer(c, data)
    c.showPage()
    c.save()
