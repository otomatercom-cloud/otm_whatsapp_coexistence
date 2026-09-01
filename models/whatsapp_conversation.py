# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OtmWhatsappConversation(models.Model):
    _name = "otm.whatsapp.conversation"
    _description = "WhatsApp Conversation"
    _inherit = ["mail.thread"]
    _rec_name = "name"
    _order = "last_message_date desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(related="phone_id.company_id", store=True, index=True)

    phone_id = fields.Many2one(
        "otm.whatsapp.phone", string="WhatsApp Number", required=True, index=True,
        ondelete="restrict",
    )
    contact_id = fields.Many2one(
        "otm.whatsapp.contact", string="WhatsApp Contact", required=True, index=True,
        ondelete="restrict",
    )

    assigned_user_id = fields.Many2one("res.users", string="Assigned To", tracking=True)
    assigned_team_id = fields.Many2one("lead.team", string="Team", tracking=True)

    status = fields.Selection(
        [("open", "Open"), ("pending", "Pending"), ("closed", "Closed")],
        default="open",
        tracking=True,
    )
    unread_count = fields.Integer(default=0)
    last_message = fields.Text(readonly=True)
    last_message_date = fields.Datetime(readonly=True, index=True)

    partner_id = fields.Many2one(related="contact_id.partner_id", store=True, readonly=True)
    lead_id = fields.Many2one(related="contact_id.lead_id", store=True, readonly=True)

    message_ids = fields.One2many("otm.whatsapp.message", "conversation_id", string="Messages")
    message_count = fields.Integer(compute="_compute_message_count")

    _phone_contact_uniq = models.Constraint(
        "unique(phone_id, contact_id)",
        "A conversation between this WhatsApp number and this contact already exists.",
    )

    @api.depends("contact_id", "phone_id.display_phone_number")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s (%s)" % (
                rec.contact_id.name or rec.contact_id.phone or "",
                rec.phone_id.display_phone_number or rec.phone_id.name or "",
            )

    @api.depends("message_ids")
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    @api.model
    def get_or_create(self, phone_id, contact_id):
        """Get-or-create guard - never a raw create, avoids duplicate conversation
        rows on concurrent/duplicate webhook delivery for the same pair."""
        conv = self.search(
            [("phone_id", "=", phone_id), ("contact_id", "=", contact_id)], limit=1
        )
        if conv:
            return conv
        return self.create({"phone_id": phone_id, "contact_id": contact_id})

    def action_close(self):
        self.write({"status": "closed"})

    def action_reopen(self):
        self.write({"status": "open"})

    def mark_read(self):
        self.write({"unread_count": 0})
