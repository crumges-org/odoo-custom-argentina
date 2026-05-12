# -*- coding: utf-8 -*-

from odoo import fields, models, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_auto_invoice = fields.Boolean(
        related='company_id.auto_invoice',
        string="POS auto invoice",
        readonly=False
    )
    pos_receipt_invoice_number = fields.Boolean(
        related='company_id.receipt_invoice_number',
        string="Receipt show invoice number",
        readonly=False
    )
    pos_receipt_customer_vat = fields.Boolean(
        related='company_id.receipt_customer_vat',
        string="Receipt show customer VAT",
        readonly=False
    )
    pos_receipt_customer_name = fields.Boolean(
        related='pos_config_id.receipt_customer_name',
        string="Receipt show customer Name",
        readonly=False
    )
    pos_receipt_customer_document_type = fields.Boolean(
        related='pos_config_id.receipt_customer_document_type',
        string="Receipt show customer Document Type",
        readonly=False
    )
    pos_receipt_customer_identification = fields.Boolean(
        related='pos_config_id.receipt_customer_identification',
        string="Receipt show customer Identification",
        readonly=False
    )
    pos_receipt_customer_address = fields.Boolean(
        related='pos_config_id.receipt_customer_address',
        string="Receipt show customer Address",
        readonly=False
    )
    pos_receipt_customer_phone = fields.Boolean(
        related='pos_config_id.receipt_customer_phone',
        string="Receipt show customer Phone",
        readonly=False
    )
    pos_receipt_customer_email = fields.Boolean(
        related='pos_config_id.receipt_customer_email',
        string="Receipt show customer Email",
        readonly=False
    )
    
    pos_anonymous_partner_id = fields.Many2one(
        related='pos_config_id.pos_anonymous_partner_id',
        readonly=False
    )
    
    pos_auto_partner = fields.Boolean(
        related='pos_config_id.pos_auto_partner',
        readonly=False
    )
    
    pos_anonymous_payment_method_ids = fields.Many2many(
        related='pos_config_id.pos_anonymous_payment_method_ids',
        readonly=False
    )
    
    pos_use_other_receipt_address = fields.Boolean(
        related='pos_config_id.pos_use_other_receipt_address',
        readonly=False
    )

    pos_receipt_other_address = fields.Selection(
        related='pos_config_id.pos_receipt_other_address',
        readonly=False
    )

