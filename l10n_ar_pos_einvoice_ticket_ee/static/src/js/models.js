/** @odoo-module */

console.log("[DEBUG] Loading l10n_ar_pos_einvoice_ticket_ee models.js");

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { onWillDestroy, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

// Patch para ProductScreen para anular el seteo forzado del Consumidor Final de la localización argentina
patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            // Revertir la acción forzada de l10n_ar_pos si el usuario desactivó pos_auto_partner
            if (this.pos.isArgentineanCompany() && !this.pos.config.pos_auto_partner) {
                const order = this.pos.get_order();
                // Si la localización lo asignó recientemente y no tiene líneas o es el inicio de la orden:
                if (order && order.get_partner() && order.get_partner().id === this.pos.session._consumidor_final_anonimo_id) {
                    order.set_partner(false);
                }
            }
        });
    }
});

// Patch para el PaymentScreen para establecer la facturación automática
patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);

        // Aplicar facturación automática después de la inicialización
        const autoInvoiceTimer = setTimeout(() => {
            const pos = this.env.services.pos;
            if (pos && pos.company && pos.company.auto_invoice) {
                const order = pos.get_order();
                if (order) {
                    // Establecer la propiedad directamente para evitar problemas con el método
                    order.to_invoice = true;

                    // Forzar actualización de la interfaz si es necesario
                    // En OWL, los cambios reactivos deberían actualizar la UI automáticamente
                    this.render(true);
                }
            }
        }, 300);

        // Limpiamos el timer al desmontar
        onWillDestroy(() => clearTimeout(autoInvoiceTimer));
    },

    onMounted() {
        if (typeof super.onMounted === 'function') {
            super.onMounted();
        }
        // Anular la facturación forzada de l10n_ar_pos si auto_invoice está desactivado
        if (this.pos.isArgentineanCompany() && !this.pos.company.auto_invoice) {
            if (this.currentOrder) {
                this.currentOrder.set_to_invoice(false);
            }
        }
    },

    getFilteredPaymentMethods() {
        const methods = this.payment_methods_from_config || [];
        const partner = this.currentOrder && this.currentOrder.get_partner();

        if (partner && this.pos.config.pos_anonymous_partner_id) {
            const anonConfig = this.pos.config.pos_anonymous_partner_id;
            const anonId = Array.isArray(anonConfig) ? anonConfig[0] : (typeof anonConfig === 'object' ? anonConfig.id : anonConfig);

            if (anonId === partner.id) {
                const allowedMethodIds = this.pos.config.pos_anonymous_payment_method_ids || [];
                if (allowedMethodIds.length > 0) {
                    // Extraer los IDs ya que Odoo a veces envía objetos o arrays por rpc en los m2m
                    const allowedIds = allowedMethodIds.map(m => typeof m === 'object' ? m.id : m);
                    return methods.filter(pm => allowedIds.includes(pm.id));
                }
            }
        }
        return methods;
    }
});

// Patch para PosStore
// Patch para PosStore
patch(PosStore.prototype, {
    // Lo importante: actualizar el método add_new_order para establecer la facturación
    add_new_order() {
        const order = super.add_new_order(...arguments);
        // Aplicar auto-factura si está configurado
        if (this.company && this.company.auto_invoice) {
            // Usar un pequeño retraso para asegurar que la UI esté lista
            setTimeout(() => {
                order.to_invoice = true;
                // También usar el método estándar si está disponible
                if (typeof order.set_to_invoice === 'function') {
                    order.set_to_invoice(true);
                }
            }, 100);
        }
        return order;
    }
});

// Patch para ReceiptScreen para que se actualice cuando llega el número de factura
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { useService } from "@web/core/utils/hooks";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.render = useState({ count: 0 }); // Estado local para forzar renderizado

        // Intervalo para verificar si llegó el número de factura
        // Esto es necesario porque el cambio en el modelo (PosOrder) no dispara automáticamente 
        // el re-renderizado de este componente específico en Odoo 18
        this.invoiceCheckInterval = setInterval(() => {
            const order = this.currentOrder;
            if (order && order.invoice_number && !this.invoice_number_displayed) {
                this.invoice_number_displayed = order.invoice_number;
                this.render.count++; // Forzar actualización de la UI
                // console.log('[DEBUG] Invoice number received, refreshing receipt screen');
            }
        }, 500);

        onWillUnmount(() => {
            if (this.invoiceCheckInterval) {
                clearInterval(this.invoiceCheckInterval);
            }
        });
    }
});

// Patch para PosOrder (antes Order)
// Patch para PosOrder (antes Order)
patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);

        // 1. Lógica de Auto-Facturación
        this._setupAutoInvoiceHook();

        // 2. Lógica de Carga de Datos de Factura (desde backend via _loader_params)
        // Estos campos son cargados automáticamente si están en el modelo JS, 
        // pero validamos explicitamente por si acaso o para transformaciones.

        this.l10n_ar_afip_auth_code = vals.l10n_ar_afip_auth_code;
        this.l10n_ar_afip_auth_code_due = vals.l10n_ar_afip_auth_code_due;
        this.l10n_ar_qr_code_base64 = vals.l10n_ar_qr_code_base64;

        // Mapeos de conveniencia
        this.invoice_number = vals.l10n_ar_invoice_display_name;
        this.l10n_ar_invoice_date = vals.l10n_ar_invoice_date;

        this.l10n_latam_document_type_id_name = vals.l10n_latam_document_type_name;
        this.l10n_latam_document_type_id_code = vals.l10n_latam_document_type_code;
        this.l10n_latam_document_report_name = vals.l10n_latam_document_report_name;
        this.invoice_letter = vals.l10n_ar_invoice_letter;

        this.terms_and_conditions = vals.l10n_ar_invoice_terms;
        this.subtotal = vals.l10n_ar_invoice_subtotal;

        // 3. Parsear JSON de impuestos complejos
        if (vals.l10n_ar_invoice_taxes_json) {
            try {
                const taxesData = JSON.parse(vals.l10n_ar_invoice_taxes_json);
                this.iva_taxes = taxesData.iva_taxes || [];
                this.other_taxes_total = taxesData.other_taxes_total || 0;
                this.detailed_taxes = taxesData.detailed_taxes || [];
            } catch (e) {
                console.error("Error parsing taxes JSON", e);
                this.iva_taxes = [];
                this.detailed_taxes = [];
                this.other_taxes_total = 0;
            }
        }
    },

    export_for_printing() {
        const result = super.export_for_printing(...arguments);

        result.headerData = result.headerData || {};

        // Datos básicos
        result.headerData.pos_name = this.config.name || '';
        result.headerData.pos_street = this.config.street || '';
        result.headerData.date = result.date || '';

        // Reemplazar nombre de empresa en el ticket si es dirección tipo diario
        if (this.config.pos_use_other_receipt_address && this.config.pos_receipt_other_address === 'journal' && this.config.pos_custom_name) {
            if (result.headerData && result.headerData.company) {
                // Clonamos la compañía para no mutar el original en el store
                result.headerData.company = { ...result.headerData.company, name: this.config.pos_custom_name };
            }
        }

        // Número de factura de la compañía y datos fiscales argentinos
        if (this.company) {
            // Siempre mostrar el número de factura y CUIT (Requerimiento de usuario: opción siempre activa)
            result.headerData.receipt_invoice_number = true;
            result.receipt_invoice_number = true;

            // Datos fiscales de la compañía para el encabezado del ticket
            result.headerData.l10n_ar_gross_income_number = this.company.l10n_ar_gross_income_number || '';
            result.headerData.l10n_ar_afip_start_date = this.company.l10n_ar_afip_start_date || '';
        }

        // Configuración dinámica de detalles del cliente en el ticket
        if (this.config) {
            result.headerData.receipt_customer_name = this.config.receipt_customer_name;
            result.headerData.receipt_customer_document_type = this.config.receipt_customer_document_type;
            result.headerData.receipt_customer_identification = this.config.receipt_customer_identification;
            result.headerData.receipt_customer_address = this.config.receipt_customer_address;
            result.headerData.receipt_customer_phone = this.config.receipt_customer_phone;
            result.headerData.receipt_customer_email = this.config.receipt_customer_email;
        }

        const partner = this.get_partner();
        if (partner) {
            // Clonamos el partner para inyectar campos string sin modificar el original
            const receiptPartner = { ...partner };

            // Helper function para extraer el nombre de forma segura sin importar el tipo de ORM de Odoo 18
            const resolveName = (val, modelName) => {
                if (!val) return "";
                if (typeof val === 'object' && val.name) return val.name; // Si ya es un Record (M2O object)
                if (Array.isArray(val) && val.length > 1) return val[1];  // Si es del tipo array [ID, Name]

                // Si es un Integer ID, lo buscamos en el store
                if (this.models && this.models[modelName]) {
                    const record = this.models[modelName].get(val);
                    if (record && record.name) return record.name;
                }
                return "";
            };

            // Resolver Tipo de Documento, Responsabilidad AFIP, Provincia y País
            receiptPartner.l10n_latam_identification_type_name = resolveName(partner.l10n_latam_identification_type_id, 'l10n_latam.identification.type');
            receiptPartner.l10n_ar_afip_responsibility_type_name = resolveName(partner.l10n_ar_afip_responsibility_type_id, 'l10n_ar.afip.responsibility.type');
            receiptPartner.state_name = resolveName(partner.state_id, 'res.country.state');
            receiptPartner.country_name = resolveName(partner.country_id, 'res.country');

            // Check if this partner is the configured anonymous partner
            let isAnon = false;
            const anonConfig = this.config.pos_anonymous_partner_id;
            if (anonConfig) {
                const anonId = Array.isArray(anonConfig) ? anonConfig[0] : (typeof anonConfig === 'object' ? anonConfig.id : anonConfig);
                if (anonId === partner.id) {
                    isAnon = true;
                }
            }
            receiptPartner.is_anonymous_customer = isAnon;

            result.headerData.partner = receiptPartner;
        }

        // Datos de Factura Electrónica Argentina
        if (this.invoice_number) {
            // Descomponer número de factura "00001-00000001"
            // Odoo suele enviarlo completo. El formato estándar es "A 0001-00000001" o similar en display_name
            const invoice_number_full = this.invoice_number;

            // Intentar extraer letra y número si el formato es estándar
            // Ejemplo: "Factura A 0001-00000001"
            let invoice_letter = this.invoice_letter || '';
            let invoice_number_clean = invoice_number_full;

            // Si no tenemos la letra mapeada, intentamos deducirla o usar la del backend
            result.headerData.invoice_number = invoice_number_clean;
            result.headerData.invoice_letter = invoice_letter;
            result.invoice_letter = invoice_letter;

            // Datos de comprobante
            result.headerData.l10n_latam_document_type_id_code = this.l10n_latam_document_type_id_code || '';
            result.headerData.l10n_latam_document_name = this.l10n_latam_document_type_id_name || '';
            result.headerData.l10n_latam_document_report_name = this.l10n_latam_document_report_name || '';
            result.l10n_latam_document_report_name = this.l10n_latam_document_report_name || '';

            // Datos AFIP
            result.l10n_ar_cae = this.l10n_ar_afip_auth_code || '';
            result.l10n_ar_cae_due_date = this.l10n_ar_afip_auth_code_due || '';
            result.l10n_ar_qr_code_base64 = this.l10n_ar_qr_code_base64 || '';
            result.terms_and_conditions = this.terms_and_conditions || '';

            // Impuestos
            result.iva_taxes = this.iva_taxes || [];
            result.other_taxes_total = this.other_taxes_total || 0;
            result.subtotal = this.subtotal || 0;
            result.detailed_taxes = this.detailed_taxes || [];
        }

        if (result.total_with_tax === undefined || result.total_with_tax === null) {
            result.total_with_tax = 0;
        }

        return result;
    },

    _setupAutoInvoiceHook() {
        setTimeout(() => {
            if (this.company && this.company.auto_invoice) {
                if (this.finalized) return;

                this.to_invoice = true;
                if (typeof this.set_to_invoice === 'function') {
                    try {
                        this.set_to_invoice(true);
                    } catch (e) {
                        console.warn('[DEBUG] Error setting to_invoice:', e);
                    }
                }
            }
        }, 300);
    },

    set_client(client) {
        const result = super.set_client(...arguments);
        this._setupAutoInvoiceHook();
        return result;
    }
});
