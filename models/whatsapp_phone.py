# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OtmWhatsappPhone(models.Model):
    """One WhatsApp Business mobile number connected under the (single)
    Meta integration. Every inbound webhook event and every outbound
    send is scoped to exactly one of these records via `phone_number_id`
    (the Meta identifier), never a fallback/default number.
    """

    _name = "otm.whatsapp.phone"
    _description = "WhatsApp Phone Number"
    _inherit = ["mail.thread"]
    _rec_name = "name"
    _order = "sequence, id"

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        related="integration_id.company_id", store=True, index=True, readonly=True
    )

    integration_id = fields.Many2one(
        "otm.whatsapp.integration",
        string="Meta Integration",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # Meta identifiers
    phone_number_id = fields.Char(
        string="Phone Number ID", required=True, index=True,
        help="Meta's phone_number_id - used to route inbound webhooks and select the "
        "outbound sending endpoint. This is the single most important field in the "
        "whole module.",
    )
    display_phone_number = fields.Char(string="Display Phone Number", tracking=True)
    verified_name = fields.Char(string="Verified Business Name")
    quality_rating = fields.Char(string="Quality Rating")

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("connected", "Connected"),
            ("suspended", "Suspended"),
            ("error", "Error"),
        ],
        default="draft",
        tracking=True,
    )
    coexistence_status = fields.Selection(
        [
            ("not_connected", "Not Connected"),
            ("pending", "Pending"),
            ("enabled", "Coexistence Enabled"),
            ("platform_only", "Platform Connected (No Coexistence)"),
            ("error", "Error"),
        ],
        default="not_connected",
        tracking=True,
        help="Reflects Meta's actual coexistence state for this number - never assumed.",
    )
    is_default = fields.Boolean(string="Default Number")

    connected_date = fields.Datetime(readonly=True)
    last_sync = fields.Datetime(readonly=True)
    last_webhook = fields.Datetime(readonly=True)

    team_id = fields.Many2one(
        "lead.team", string="Assigned Team",
        help="custom_leads_19's own lead.team model - not crm.team, which this module "
        "no longer depends on.",
    )
    user_ids = fields.Many2many(
        "res.users", "otm_whatsapp_phone_user_rel", "phone_id", "user_id",
        string="Assigned Users",
    )

    conversation_ids = fields.One2many(
        "otm.whatsapp.conversation", "phone_id", string="Conversations"
    )
    conversation_count = fields.Integer(compute="_compute_conversation_count")
    unread_count = fields.Integer(compute="_compute_unread_count")

    _phone_number_id_uniq = models.Constraint(
        "unique(phone_number_id)",
        "This Meta Phone Number ID is already connected to another record.",
    )

    @api.depends("conversation_ids")
    def _compute_conversation_count(self):
        for rec in self:
            rec.conversation_count = len(rec.conversation_ids)

    @api.depends("conversation_ids.unread_count")
    def _compute_unread_count(self):
        grouped = self.env["otm.whatsapp.conversation"]._read_group(
            [("phone_id", "in", self.ids), ("unread_count", ">", 0)],
            groupby=["phone_id"],
            aggregates=["unread_count:sum"],
        )
        data = {phone.id: total for phone, total in grouped}
        for rec in self:
            rec.unread_count = data.get(rec.id, 0)

    def action_activate(self):
        self.write({"status": "connected", "active": True, "connected_date": fields.Datetime.now()})

    def action_deactivate(self):
        self.write({"status": "suspended", "active": False})

    def get_client(self):
        self.ensure_one()
        return self.integration_id._get_client()
