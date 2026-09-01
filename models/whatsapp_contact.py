# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models


class OtmWhatsappContact(models.Model):
    _name = "otm.whatsapp.contact"
    _description = "WhatsApp Contact"
    _inherit = ["mail.thread"]
    _rec_name = "name"

    name = fields.Char(required=True, tracking=True)
    wa_id = fields.Char(string="WhatsApp ID", index=True, help="Meta's wa_id for this contact.")
    phone = fields.Char(required=True, tracking=True)
    normalized_phone = fields.Char(index=True, readonly=True)
    profile_name = fields.Char(string="WhatsApp Profile Name")

    partner_id = fields.Many2one("res.partner", string="Contact")
    lead_id = fields.Many2one(
        "leads.logic", string="Lead",
        help="Linked custom_leads_19 lead record.",
    )
    # NOTE: this module does not `depends` on student_details_19/admission modules,
    # so a Many2one to those models would fail _setup_fields at install (erp-tooling
    # finding #29). Kept as a plain integer hook (record id) + a helper computed
    # widget-friendly field; wire a real Many2one in a thin bridge module instead,
    # e.g. `otm_whatsapp_student_bridge`, once you confirm the exact model names.
    student_details_id = fields.Integer(
        string="Student Record ID (otm.student.details)",
        help="Numeric id into student_details_19's otm.student.details, set by an "
        "external bridge module. Kept as a bare integer here so this module has no "
        "hard dependency on student_details_19.",
    )
    admission_reference = fields.Char(
        string="Admission Reference",
        help="Free-text hook for admission integration until a bridge module wires a "
        "real Many2one.",
    )

    opt_in_status = fields.Selection(
        [("unknown", "Unknown"), ("opted_in", "Opted In"), ("opted_out", "Opted Out")],
        default="unknown",
        tracking=True,
    )

    conversation_ids = fields.One2many(
        "otm.whatsapp.conversation", "contact_id", string="Conversations"
    )

    _phone_uniq = models.Constraint(
        "unique(normalized_phone)", "A contact already exists for this phone number."
    )

    @api.model
    def normalize_phone(self, phone):
        if not phone:
            return False
        digits = re.sub(r"\D", "", phone)
        return digits

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("phone") and not vals.get("normalized_phone"):
                vals["normalized_phone"] = self.normalize_phone(vals["phone"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("phone"):
            vals["normalized_phone"] = self.normalize_phone(vals["phone"])
        return super().write(vals)

    @api.model
    def get_or_create_from_wa(self, wa_id, phone, profile_name=False):
        """Get-or-create guard (never a raw create) to avoid duplicate contacts
        on repeated/duplicate webhook delivery of the same wa_id."""
        normalized = self.normalize_phone(phone)
        contact = self.search(
            ["|", ("wa_id", "=", wa_id), ("normalized_phone", "=", normalized)], limit=1
        )
        if contact:
            update_vals = {}
            if profile_name and contact.profile_name != profile_name:
                update_vals["profile_name"] = profile_name
            if not contact.wa_id and wa_id:
                update_vals["wa_id"] = wa_id
            if update_vals:
                contact.write(update_vals)
            return contact
        return self.create(
            {
                "name": profile_name or phone,
                "wa_id": wa_id,
                "phone": phone,
                "profile_name": profile_name,
            }
        )
