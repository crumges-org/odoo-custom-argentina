# -*- coding: utf-8 -*-
from odoo import models, api, fields

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_order(self):
        result = super()._loader_params_pos_order()
        result['search_params']['fields'].extend([
            'l10n_ar_afip_auth_code',
            'l10n_ar_afip_auth_code_due',
            'l10n_ar_afip_qr_code',
            'l10n_ar_qr_code_base64',
            'l10n_latam_document_type_id',
            'l10n_ar_invoice_taxes_json',
            'l10n_ar_invoice_display_name', # Instead of invoice_number
            'l10n_ar_invoice_date',
        ])
        return result

    def _loader_params_pos_config(self):
        result = super()._loader_params_pos_config()
        result['search_params']['fields'].extend([
            'pos_auto_partner',
            'pos_custom_address',
            'pos_custom_name',
        ])
        return result
