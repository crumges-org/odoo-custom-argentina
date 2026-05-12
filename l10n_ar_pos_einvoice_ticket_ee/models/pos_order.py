# -*- coding: utf-8 -*-
from odoo import api, models, fields
import logging
import base64
import qrcode
from io import BytesIO
import json
from html import unescape
import re

_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    _inherit = "pos.order"

    l10n_ar_afip_qr_code = fields.Char(related='account_move.l10n_ar_afip_qr_code', string="QR Code AFIP")
    l10n_ar_afip_auth_code = fields.Char(related='account_move.l10n_ar_afip_auth_code', string="CAE")
    l10n_ar_afip_auth_code_due = fields.Date(related='account_move.l10n_ar_afip_auth_code_due', string="Vencimiento CAE")
    l10n_latam_document_type_id = fields.Many2one(related='account_move.l10n_latam_document_type_id', string="Tipo de Comprobante")
    
    # Campos adicionales para facilitar el acceso en JS sin cargar todo el modelo l10n_latam.document.type
    l10n_latam_document_type_name = fields.Char(related='l10n_latam_document_type_id.name')
    l10n_latam_document_type_code = fields.Char(related='l10n_latam_document_type_id.code')
    l10n_latam_document_report_name = fields.Char(related='l10n_latam_document_type_id.report_name')
    l10n_ar_invoice_letter = fields.Selection(related='l10n_latam_document_type_id.l10n_ar_letter')

    l10n_ar_invoice_display_name = fields.Char(related='account_move.name', string="Número de Factura")
    l10n_ar_invoice_date = fields.Date(related='account_move.invoice_date', string="Fecha Factura")
    
    l10n_ar_qr_code_base64 = fields.Text(compute='_compute_l10n_ar_qr_code_base64', string="QR Base64")
    l10n_ar_invoice_taxes_json = fields.Text(compute='_compute_l10n_ar_invoice_taxes_json', string="Impuestos JSON")
    l10n_ar_invoice_terms = fields.Text(compute='_compute_l10n_ar_invoice_terms', string="Términos y Condiciones")
    l10n_ar_invoice_subtotal = fields.Monetary(related='account_move.amount_untaxed', string="Subtotal Factura")

    def _generate_qr_base64(self, qr_text):
        """Genera una imagen QR en base64 a partir de un texto."""
        if not qr_text:
            return ''
        qr = qrcode.QRCode(box_size=3)
        qr.add_data(qr_text)
        qr.make(fit=True)
        img = qr.make_image()
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    def _html_to_text(self, html_content):
        """Convierte HTML a texto plano (elimina las etiquetas HTML)"""
        if not html_content:
            return ''
        # Desencodifica entidades HTML como &amp; a &
        try:
            text = unescape(html_content)
        except:
            text = html_content
        # Elimina todas las etiquetas HTML
        text = re.sub(r'<[^>]+>', '', text)
        return text

    @api.depends('l10n_ar_afip_qr_code')
    def _compute_l10n_ar_qr_code_base64(self):
        for order in self:
            order.l10n_ar_qr_code_base64 = self._generate_qr_base64(order.l10n_ar_afip_qr_code or '')

    @api.depends('account_move', 'account_move.invoice_payment_term_id')
    def _compute_l10n_ar_invoice_terms(self):
        for order in self:
            terms = ''
            invoice = order.account_move
            if invoice:
                if invoice.narration:
                    terms = self._html_to_text(invoice.narration)
                elif invoice.invoice_payment_term_id and invoice.invoice_payment_term_id.note:
                    terms = self._html_to_text(invoice.invoice_payment_term_id.note)
                elif self.env.company.invoice_terms:
                    terms = self._html_to_text(self.env.company.invoice_terms)
            order.l10n_ar_invoice_terms = terms

    @api.depends('account_move', 'account_move.invoice_line_ids', 'account_move.invoice_line_ids.tax_ids')
    def _compute_l10n_ar_invoice_taxes_json(self):
        for order in self:
            data = {
                'iva_taxes': [],
                'other_taxes': [], # Solo para info interna
                'other_taxes_total': 0,
                'detailed_taxes': []
            }
            
            invoice = order.account_move
            if invoice:
                iva_taxes = {}  # Para agrupar IVA por alícuota
                other_taxes = []  # Para otros impuestos
                
                # Recorrer líneas de factura y sus impuestos
                for line in invoice.invoice_line_ids:
                    base_imponible = line.price_subtotal
                    
                    for tax in line.tax_ids:
                        # Verificar si es un impuesto de IVA
                        is_iva = tax.tax_group_id and tax.tax_group_id.l10n_ar_vat_afip_code in ['3', '4', '5', '6', '8', '9']
                        
                        if is_iva:
                            # Es un impuesto de IVA
                            alicuota = tax.amount
                            tax_amount = base_imponible * (alicuota / 100.0)
                            
                            # Agrupar por alícuota
                            if alicuota not in iva_taxes:
                                iva_taxes[alicuota] = {
                                    'id': f'iva_{alicuota}',
                                    'alicuota': alicuota,
                                    'amount': 0,
                                    'base_imponible': 0,
                                    'name': tax.name,
                                    'invoice_label': tax.invoice_label or tax.name
                                }
                            
                            iva_taxes[alicuota]['amount'] += tax_amount
                            iva_taxes[alicuota]['base_imponible'] += base_imponible
                        else:
                            # Otro tipo de impuesto (no IVA)
                            tax_amount = base_imponible * (tax.amount / 100.0)
                            
                            # Verificar si ya existe en la lista
                            existing_tax = next((t for t in other_taxes if t.get('tax_id') == tax.id), None)
                            
                            if existing_tax:
                                existing_tax['amount'] += tax_amount
                            else:
                                other_taxes.append({
                                    'id': f'tax_{tax.id}',
                                    'tax_id': tax.id,
                                    'name': tax.name,
                                    'amount': tax_amount,
                                    'invoice_label': tax.invoice_label or tax.name
                                })
                
                # Convertir diccionario de IVA a lista
                iva_tax_list = list(iva_taxes.values())
                iva_tax_list.sort(key=lambda x: x['alicuota'], reverse=True)
                
                # Calcular el total de otros impuestos
                other_taxes_total = sum(tax['amount'] for tax in other_taxes)
                
                data['iva_taxes'] = iva_tax_list
                data['other_taxes_total'] = other_taxes_total
                
                # Combinar todos los impuestos para detailed_taxes
                tax_details = []
                for iva in iva_tax_list:
                    tax_details.append({
                        'id': iva['id'],
                        'name': iva['name'],
                        'invoice_label': iva['invoice_label'],
                        'amount': iva['amount'],
                        'is_iva': True,
                        'alicuota': iva['alicuota']
                    })
                
                for tax in other_taxes:
                    tax_details.append({
                        'id': tax['id'],
                        'name': tax['name'],
                        'invoice_label': tax['invoice_label'],
                        'amount': tax['amount'],
                        'is_iva': False
                    })
                
                tax_details.sort(key=lambda x: x['amount'], reverse=True)
                data['detailed_taxes'] = tax_details
            
            order.l10n_ar_invoice_taxes_json = json.dumps(data)
