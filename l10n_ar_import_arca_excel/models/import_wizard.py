import base64
import io
import json
import logging
from datetime import datetime
from odoo import models, fields, api, _
from markupsafe import Markup
from odoo.exceptions import UserError
import re

_logger = logging.getLogger(__name__)

try:
    import openpyxl
except ImportError:
    _logger.error("OpenPyXL not installed")

class L10nArImportArcaWizard(models.TransientModel):
    _name = 'l10n_ar.arca.import.wizard'
    _description = 'Asistente de Importación ARCA'

    file_data = fields.Binary(string='Archivo Excel', required=True)
    filename = fields.Char(string='Nombre Archivo')
    import_type = fields.Selection([
        ('in_invoice', 'Facturas Recibidas (Proveedores)'),
        ('out_invoice', 'Facturas Emitidas (Clientes)')
    ], string='Tipo de Importación', required=True, default='in_invoice')
    
    default_journal_id = fields.Many2one(
        'account.journal', 
        string='Diario por Defecto', 
        domain="[('type', '=', 'purchase')]"
    )

    line_ids = fields.One2many('l10n_ar.arca.import.line', 'wizard_id', string='Líneas')
    
    state = fields.Selection([
        ('upload', 'Carga'),
        ('review', 'Revisión'),
        ('done', 'Hecho')
    ], default='upload', string='Estado')

    @api.onchange('import_type')
    def _onchange_import_type(self):
        if self.import_type == 'out_invoice':
            return {'domain': {'default_journal_id': [('type', '=', 'sale')]}}
        else:
            return {'domain': {'default_journal_id': [('type', '=', 'purchase')]}}

    def _normalize_cuit(self, cuit):
        if not cuit:
            return False
        return str(cuit).replace('-', '').replace(' ', '')
    
    def _get_document_type(self, doc_name):
        # Mapeo básico de nombres ARCA a Document Types de Odoo
        # ARCA: "1 - Factura A", "6 - Factura B", "11 - Factura C"
        # Odoo l10n_ar: buscar por codigo
        code_match = re.match(r'^(\d+)\s-', doc_name)
        if code_match:
            code = code_match.group(1)
            # Buscar document type por codigo AFIP
            doc_type = self.env['l10n_latam.document.type'].search([
                ('code', '=', code),
                ('country_id.code', '=', 'AR')
            ], limit=1)
            return doc_type
        return False

    def _find_tax(self, amount, type_tax_use):
        # Búsqueda aproximada de impuestos por monto
        # ARCA columns: "IVA 21%", "IVA 10,5%", "IVA 27%"
        # amount es el valor porcentual (21.0, 10.5)
        # Buscar impuesto activo de ese tipo
        taxes = self.env['account.tax'].search([
            ('type_tax_use', '=', type_tax_use),
            ('amount', '=', amount),
            ('amount_type', '=', 'percent'),
            ('country_id.code', '=', 'AR'),
            ('active', '=', True)
        ])
        return taxes[0] if taxes else False

    def action_analyze(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Por favor suba un archivo."))
            
        if 'openpyxl' not in globals():
            raise UserError(_("La librería 'openpyxl' no está instalada. Por favor contacte al administrador."))

        wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(self.file_data)), data_only=True)
        ws = wb.active # Asumimos primera hoja
        
        # Headers mapping (based on provided sample)
        # We need to map column index to field
        headers = {}
        header_row_idx = 1 # 0-indexed is 1??? No, openpyxl is 1-indexed for rows usually, but iter_rows gives tuples.
        # Let's simple iterate and find header row
        
        rows = list(ws.iter_rows(values_only=True))
        
        start_row = 0
        for i, row in enumerate(rows):
            if row and 'Fecha' in row and 'Tipo' in row:
                start_row = i + 1
                # Map headers
                for col_idx, cell_val in enumerate(row):
                    headers[cell_val] = col_idx
                break
        
        if not headers:
            raise UserError(_("No se encontró la fila de encabezados (Fecha, Tipo, etc)."))

        # --- VALIDACIÓN CUIT COMPAÑÍA ---
        # Fila 0, Celda 0 usualmente contiene: "Mis Comprobantes ... - CUIT 30718858514"
        try:
            # Re-leer fila 0 para asegurar
            first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
            header_title = first_row[0]
            if header_title and 'CUIT' in str(header_title):
                # Extraer CUIT (últimos dígitos o regex)
                cuit_match = re.search(r'CUIT\s+(\d+)', str(header_title))
                if cuit_match:
                    excel_cuit = cuit_match.group(1)
                    # Normalizar Company CUIT: Remover AR, guiones y espacios
                    company_vat = self.env.company.vat or ''
                    # A veces l10n_ar agrega prefix AR or similiar
                    company_cuit = re.sub(r'\D', '', company_vat)
                    
                    if company_cuit and excel_cuit != company_cuit:
                        raise UserError(_(
                            "El CUIT del archivo ({}) no coincide con el CUIT de la compañía actual ({}).\n"
                            "Por favor verifique que está importando el archivo correcto."
                        ).format(excel_cuit, company_cuit))
        except UserError:
            raise
        except Exception as e:
            _logger.warning(f"No se pudo validar el CUIT del encabezado: {e}")
            # No bloqueamos si falla el parseo del título, pero logueamos.

        lines_values = []
        
        # Pre-fetch generic data
        company_currency = self.env.company.currency_id
        
        for row_idx in range(start_row, len(rows)):
            row = rows[row_idx]
            if not row[headers.get('Fecha')]:
                continue

            # Extraer Datos Básicos
            date_str = row[headers['Fecha']]
            # Parse Date dd/mm/yyyy
            try:
                date = datetime.strptime(date_str, '%d/%m/%Y').date() if isinstance(date_str, str) else date_str
            except:
                date = fields.Date.today()

            doc_type_name = row[headers.get('Tipo', -1)]
            pos = row[headers.get('Punto de Venta', -1)]
            number_from = row[headers.get('Número Desde', -1)]
            # number_to = row[headers.get('Número Hasta')]
            
            cuit_col = 'Nro. Doc. Emisor' if self.import_type == 'in_invoice' else 'Nro. Doc. Receptor'
            name_col = 'Denominación Emisor' if self.import_type == 'in_invoice' else 'Denominación Receptor'
            
            cuit_raw = row[headers.get(cuit_col)]
            cuit = self._normalize_cuit(cuit_raw)
            partner_name = row[headers.get(name_col)]
            
            # CAE Extraction
            afip_auth_code = row[headers.get('Cód. Autorización')] if headers.get('Cód. Autorización') is not None else False
            
            amount_total = row[headers.get('Imp. Total', -1)]
            
            # --- VALIDACIONES Y RESOLUCIONES ---
            status = 'ready'
            error_msgs = []
            
            # 1. Diario
            journal = False
            if self.import_type == 'in_invoice':
                journal = self.default_journal_id
                if not journal:
                    status = 'error'
                    error_msgs.append("Falta seleccionar Diario por defecto para Compras.")
            else:
                # Ventas: Buscar por POS
                journal = self.env['account.journal'].search([
                    ('type', '=', 'sale'),
                    ('l10n_ar_afip_pos_number', '=', int(pos) if pos else 0),
                    ('company_id', '=', self.env.company.id)
                ], limit=1)
                if not journal:
                    status = 'error'
                    error_msgs.append(f"No se encontró Diario de Venta para Punto de Venta {pos}.")

            # 2. Partner (Contacto)
            partner = self.env['res.partner'].search([
                ('vat', '=', cuit),
                ('parent_id', '=', False)
            ], limit=1)
            
            if not partner and not cuit:
                 status = 'error'
                 error_msgs.append("Falta CUIT para identificar contacto.")
            
            # 3. Documento Existente
            doc_type = self._get_document_type(doc_type_name)
            move = False
            
            # Ensure headers exist
            if headers.get('Número Desde') is None:
                 # Try 'Número' if 'Número Desde' missing (some variations)
                 if headers.get('Número') is not None:
                      headers['Número Desde'] = headers['Número']
                 else:
                      raise UserError("No se encuentra columna 'Número Desde' o 'Número'")

            if doc_type and journal and partner:
                # Robust Duplicate Check
                def _parse_int_safe(val):
                    try:
                        if isinstance(val, (int, float)):
                            return int(val)
                        if isinstance(val, str):
                            # Remove dots (thousands) and keep only digits
                            val = val.replace('.', '').replace(',', '')
                            return int(re.sub(r'\D', '', val) or 0)
                        return 0
                    except:
                        return 0

                pos_int = _parse_int_safe(pos)
                num_int = _parse_int_safe(number_from)

                try:
                    pos_int = _parse_int_safe(pos)
                    num_int = _parse_int_safe(number_from)
                except Exception as e:
                    _logger.error(f"Error parsing ints for {partner.name}: {e}")
                    pos_int = 0
                    num_int = 0

                # Formatos posibles de número de documento en Odoo (AR)
                # Standard: 00002-00001234 (5 pos, 8 number)
                # Legacy: 0002-00001234 (4 pos)
                candidates = [
                    f"{pos_int:05d}-{num_int:08d}",
                    f"{pos_int:04d}-{num_int:08d}",
                ]

                domain = [
                    ('journal_id', '=', journal.id),
                    ('partner_id', '=', partner.id),
                    ('l10n_latam_document_type_id', '=', doc_type.id),
                    ('l10n_latam_document_number', 'in', candidates)
                ]
                
                move = self.env['account.move'].search(domain, limit=1)
                
                # --- SAFETY CHECK ---
                # Verificar que la factura encontrada realmente coincida con los candidatos
                # Esto es para evitar "falsos positivos" si la búsqueda se comporta de forma laxa
                if move:
                    found_number = move.l10n_latam_document_number
                    if found_number not in candidates:
                        _logger.warning(f"False Positive Detection: Search found {found_number} but expected one of {candidates}. Ignoring.")
                        move = False # IGNORAR el resultado, no es duplicado real

                # Debug log
                if move:
                     _logger.info(f"DUPLICATE FOUND: {partner.name} - Excel: {pos}-{number_from} -> Cand: {candidates} -> MATCH: {move.name} ({move.l10n_latam_document_number}) ID:{move.id}")
                else:
                     _logger.info(f"NO DUPLICATE: {partner.name} - Excel: {pos}-{number_from} -> Cand: {candidates}")

                if move:
                    status = 'exists'
                    # Enhanced Error Message for User Debugging
                    error_msgs.append(f"<b>Factura ya existe</b>: <a href='#' data-oe-model='account.move' data-oe-id='{move.id}'>{move.name}</a> (Doc: {move.l10n_latam_document_number})")

            # 4. Impuestos (Recopilar líneas)
            tax_lines = []
            # Mapeo de columnas de impuetos ARCA a tasas
            tax_mapping = {
                'IVA 21%': 21.0,
                'IVA 10,5%': 10.5,
                'IVA 27%': 27.0,
                'IVA 5%': 5.0,
                'IVA 2,5%': 2.5,
                #'IVA 0%': 0.0 # Exento or 0? 
            }
            
            # Type Tax Use verification
            type_tax_use = 'purchase' if self.import_type == 'in_invoice' else 'sale'

            invoice_lines_data = [] # Stores (tax_id, base_amount) or product line
            
            # Netos
            # ARCA has specific logic. Typically: "Neto Grav. IVA 21%", "IVA 21%"
            # We can create lines based on Netos
            
            has_taxes = False
            for col_name, rate in tax_mapping.items():
                neto_col = f"Neto Grav. {col_name}" if col_name != 'IVA 0%' else 'Neto Grav. IVA 0%' 
                # Sometimes headers change slightly "Neto Grav. IVA 21%" matches sample
                
                if headers.get(neto_col) is not None and row[headers[neto_col]]:
                    amount_neto = row[headers[neto_col]]
                    if amount_neto:
                        tax = self._find_tax(rate, type_tax_use)
                        if not tax:
                            status = 'error'
                            error_msgs.append(f"No se encontró Impuesto {rate}% {type_tax_use}.")
                        else:
                            has_taxes = True
                            invoice_lines_data.append({
                                'price_unit': amount_neto,
                                'tax_ids': [tax.id],
                                'name': f'Importe Gravado {rate}%'
                            })
            
            # Exentos / No Gravados
            if headers.get('Neto No Gravado') is not None and row[headers['Neto No Gravado']]:
                # Need tax for No Gravado? Or just line without tax? Usually No Gravado implies specific tax in AR.
                # For simplicity, no tax or search 0%
                amount_ng = row[headers['Neto No Gravado']]
                if amount_ng:
                    invoice_lines_data.append({
                        'price_unit': amount_ng,
                        'tax_ids': [],
                        'name': 'Conceptos No Gravados'
                    })
            
            if headers.get('Op. Exentas') is not None and row[headers['Op. Exentas']]:
                 amount_ex = row[headers['Op. Exentas']]
                 if amount_ex:
                      # Find tax exento?
                      tax_ex = self.env['account.tax'].search([
                            ('type_tax_use', '=', type_tax_use),
                            ('amount', '=', 0.0),
                            ('name', 'ilike', 'Exento'),
                            ('active', '=', True)
                        ], limit=1)
                      # Fallback generic 0
                      if not tax_ex:
                           tax_ex = self.env['account.tax'].search([('type_tax_use', '=', type_tax_use), ('amount', '=', 0.0), ('active', '=', True)], limit=1)
                      
                      invoice_lines_data.append({
                        'price_unit': amount_ex,
                        'tax_ids': [tax_ex.id] if tax_ex else [],
                        'name': 'Operaciones Exentas'
                    })


            # Construct JSON for creation
            invoice_vals = {
                'ref': f"{doc_type_name} {pos}-{number_from}",
                'move_type': self.import_type,
                'invoice_date': date.strftime('%Y-%m-%d') if date else False,
                'partner_id': partner.id if partner else False, # Will need creation logic if False
                'journal_id': journal.id if journal else False,
                'l10n_latam_document_type_id': doc_type.id if doc_type else False,
                'l10n_latam_document_number': f"{int(pos):05d}-{int(number_from):08d}",
                'invoice_line_ids': [(0, 0, line) for line in invoice_lines_data]
            }
            
            if not invoice_lines_data and status == 'ready':
                 # Fallback if no specific tax columns found but total exists (Simpler inv?)
                 if amount_total:
                      invoice_vals['invoice_line_ids'] = [(0, 0, {
                          'price_unit': amount_total,
                          'tax_ids': [],
                          'name': 'Importe General'
                      })]

            lines_values.append({
                'date': date,
                'document_type_name': doc_type_name,
                'point_of_sale': pos,
                'number': number_from,
                'cuit': cuit,
                'afip_auth_code': afip_auth_code,
                'partner_name': partner_name,
                'partner_id': partner.id if partner else False,
                'journal_id': journal.id if journal else False,
                'amount_total': amount_total,
                'currency_id': company_currency.id,
                'status': status,
                'error_desc': '<br/>'.join(error_msgs) if error_msgs else False,
                'invoice_values': json.dumps(invoice_vals),
                'move_id': move.id if move else False
            })

        self.line_ids = [(5, 0, 0)] + [(0, 0, val) for val in lines_values]
        self.state = 'review'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def action_back(self):
        self.ensure_one()
        self.state = 'upload'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def action_import(self):
        self.ensure_one()
        created_moves = self.env['account.move']
        
        for line in self.line_ids:
            if line.status != 'ready':
                continue
                
            vals = json.loads(line.invoice_values)
            
            # 1. Partner Creation if needed
            if not vals.get('partner_id'):
                # Search for CUIT identification type
                cuit_type = self.env['l10n_latam.identification.type'].search([('name', '=', 'CUIT')], limit=1)
                
                # Create partner
                partner = self.env['res.partner'].create({
                    'name': line.partner_name,
                    'vat': line.cuit,
                    'company_type': 'company', # Force Company
                    'l10n_latam_identification_type_id': cuit_type.id if cuit_type else False,
                    'l10n_ar_afip_responsibility_type_id': self.env.ref('l10n_ar.res_IVARI').id, # Default to Responsable Inscripto logic might need review but ok for now
                })
                # Chatter message for partner
                partner.message_post(body=Markup(_("Partner dado de alta automáticamente por <b>Importación de Facturas ARCA</b>.")))
                
                vals['partner_id'] = partner.id
            
            # 2. Create Move
            try:
                # If we have AFIP Auth Code, we must ensure auth_mode is CAE (especially for vendor bills or offline mode)
                if line.afip_auth_code:
                    vals['l10n_ar_afip_auth_mode'] = 'CAE'
                
                move = self.env['account.move'].create(vals)
                
                # --- CHATTER & CAE LOGIC ---
                msg_body = Markup(_("Factura importada desde archivo ARCA: <b>%s</b>")) % (self.filename or 'Desconocido')
                move.message_post(body=msg_body)

                # Check AFIP Verification Type (if field exists and is configured)
                # Field on res.company: l10n_ar_afip_verification_type (selection)
                # 'not_available' means NO connection/validation needed. Anything else usually implies validation.
                # However, user said: "Si la opción... es distinta a 'No disponible' entonces tambien transcribe el CAE"
                
                if hasattr(self.env.company, 'l10n_ar_afip_verification_type'):
                    verif_type = self.env.company.l10n_ar_afip_verification_type
                    if verif_type != 'not_available' and line.afip_auth_code:
                        move.write({
                            'l10n_ar_afip_auth_code': line.afip_auth_code,
                            'l10n_ar_afip_result': 'A', # Always A for ARCA history
                        })
                        
                created_moves |= move
                line.status = 'exists'
                line.move_id = move.id
            except Exception as e:
                line.status = 'error'
                line.error_desc = str(e)
        
        # --- CREATE HISTORY RECORD ---
        if created_moves:
            self.env['l10n_ar.arca.import.history'].create({
                'name': f"Importación {fields.Datetime.now().strftime('%d/%m/%Y %H:%M')} - {self.filename or 'Sin Nombre'}",
                'filename': self.filename,
                'file_data': self.file_data,
                'import_type': self.import_type,
                'move_ids': [(6, 0, created_moves.ids)]
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Importación completada"),
                'message': _(f"Se crearon {len(created_moves)} facturas."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }
