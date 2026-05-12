# -*- coding: utf-8 -*-

from odoo import models, fields, api
class PosConfig(models.Model):
    _inherit = 'pos.config'

    receipt_customer_name = fields.Boolean(
        'Receipt show customer Name',
        default=True
    )
    receipt_customer_document_type = fields.Boolean(
        'Receipt show customer Document Type',
        default=True
    )
    receipt_customer_identification = fields.Boolean(
        'Receipt show customer Identification',
        default=True
    )
    receipt_customer_address = fields.Boolean(
        'Receipt show customer Address',
        default=True
    )
    receipt_customer_phone = fields.Boolean(
        'Receipt show customer Phone',
        default=True
    )
    receipt_customer_email = fields.Boolean(
        'Receipt show customer Email',
        default=True
    )
    
    @api.model
    def _default_anonymous_partner(self):
        return self.env.ref('l10n_ar.par_cfa', raise_if_not_found=False)

    pos_anonymous_partner_id = fields.Many2one(
        'res.partner',
        string='Anonymous Customer',
        default=_default_anonymous_partner,
        domain=[
            ('is_company', '=', False),
            ('vat', 'in', [False, '']),
            ('l10n_latam_identification_type_id.name', 'ilike', 'Sigd'),
        ],
        help="This customer will be treated as an anonymous customer on the receipt, hiding all their details except the responsibility type."
    )

    pos_auto_partner = fields.Boolean(
        'Auto assign anonymous customer',
        default=True,
        help="If AFIP localization attempts to auto-assign the Consumer Final, this option allows you to disable that behavior."
    )

    pos_anonymous_payment_method_ids = fields.Many2many(
        'pos.payment.method',
        relation='pos_config_anonymous_payment_method_rel',
        column1='pos_config_id',
        column2='payment_method_id',
        string='Anonymous Pyament Methods',
        domain=[('journal_id', '!=', False)],
        help="Payment methods allowed when the user selects the Anonymous Customer. Methods not included here will be blocked in the Point of Sale for this customer."
    )

    pos_use_other_receipt_address = fields.Boolean(
        "Usar otras direcciones en Ticket", default=False
    )

    pos_receipt_other_address = fields.Selection([
        ('journal', 'Dirección del punto de venta de facturación (Diario)'),
        ('warehouse', 'Dirección del Almacén')
    ], string='Otra Dirección Ticket', default='journal')
    
    pos_custom_address = fields.Char(string='Dirección Ticket Compute', compute='_compute_pos_custom_address', store=False)
    pos_custom_name = fields.Char(string='Compañía Ticket Compute', compute='_compute_pos_custom_name', store=False)
    pos_gross_income_number = fields.Char(
        string='IIBB Ticket Compute',
        compute='_compute_pos_fiscal_data',
        store=False
    )
    pos_afip_start_date = fields.Char(
        string='Inicio Actividades Ticket Compute',
        compute='_compute_pos_fiscal_data',
        store=False
    )

    @api.depends('company_id.l10n_ar_gross_income_number', 'company_id.l10n_ar_afip_start_date')
    def _compute_pos_fiscal_data(self):
        for config in self:
            config.pos_gross_income_number = config.company_id.l10n_ar_gross_income_number or ''
            config.pos_afip_start_date = str(config.company_id.l10n_ar_afip_start_date) if config.company_id.l10n_ar_afip_start_date else ''

    @api.depends('pos_use_other_receipt_address', 'pos_receipt_other_address', 'invoice_journal_id.l10n_ar_afip_pos_partner_id')
    def _compute_pos_custom_name(self):
        for config in self:
            if config.pos_use_other_receipt_address and config.pos_receipt_other_address == 'journal' and config.invoice_journal_id and getattr(config.invoice_journal_id, 'l10n_ar_afip_pos_partner_id', False):
                config.pos_custom_name = config.invoice_journal_id.l10n_ar_afip_pos_partner_id.name
            else:
                config.pos_custom_name = False

    @api.depends('pos_use_other_receipt_address', 'pos_receipt_other_address', 'company_id.partner_id', 'invoice_journal_id.l10n_ar_afip_pos_partner_id', 'picking_type_id.warehouse_id.partner_id')
    def _compute_pos_custom_address(self):
        for config in self:
            partner = config.company_id.partner_id
            if config.pos_use_other_receipt_address:
                if config.pos_receipt_other_address == 'journal' and config.invoice_journal_id and getattr(config.invoice_journal_id, 'l10n_ar_afip_pos_partner_id', False):
                    partner = config.invoice_journal_id.l10n_ar_afip_pos_partner_id
                elif config.pos_receipt_other_address == 'warehouse' and config.picking_type_id and config.picking_type_id.warehouse_id and config.picking_type_id.warehouse_id.partner_id:
                    partner = config.picking_type_id.warehouse_id.partner_id
            
            # Formateamos la dirección tal cual Odoo para el ticket
            address_parts = []
            if partner:
                if partner.street:
                    address_parts.append(partner.street)
                if partner.city:
                    address_parts.append(f"{partner.city}")
                if partner.state_id:
                    address_parts.append(f"{partner.state_id.name}")
                if partner.country_id:
                    address_parts.append(f"{partner.country_id.name}")
            
            config.pos_custom_address = ', '.join(address_parts)
