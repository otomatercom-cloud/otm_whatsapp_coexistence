# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LeadsLogic(models.Model):
    """Inherits custom_leads_19's real lead model.

    IMPORTANT - please confirm the phone field name: I don't have the
    custom_leads_19 source in this build environment, and I hit a real
    install-breaking bug in the previous version of this module from
    guessing a field name (`crm.lead.mobile`, which doesn't exist in
    Odoo 19 core - see erp_tooling finding #46). I'm not repeating that
    here. `_get_lead_phone()` below tries several common candidate field
    names defensively at runtime (never at @depends/install time), so
    installing this module cannot break even if none of them match your
    actual schema - it just won't find a phone number until you tell me
    the real field name, at which point I'll swap this for a proper
    `@api.depends('<real_field>')` reactive compute.
    """

    _inherit = "leads.logic"

    whatsapp_conversation_ids = fields.One2many(
        "otm.whatsapp.conversation", compute="_compute_whatsapp_conversation_ids",
        string="WhatsApp Conversations",
    )
    whatsapp_conversation_count = fields.Integer(
        compute="_compute_whatsapp_conversation_ids", string="WhatsApp Conversation Count"
    )

    _WA_PHONE_FIELD_CANDIDATES = (
        "mobile", "phone", "contact_number", "phone_number", "contact_no", "whatsapp_number",
    )

    def _get_lead_phone(self):
        """Best-effort phone lookup that never assumes a field name that
        might not exist - checks self._fields (the model's REAL, installed
        field set) before ever touching a value, so this can't raise
        AttributeError/ValueError at install or runtime no matter which
        candidate is actually present."""
        self.ensure_one()
        for fname in self._WA_PHONE_FIELD_CANDIDATES:
            if fname in self._fields:
                value = getattr(self, fname, False)
                if value:
                    return value
        return False

    @api.depends()
    def _compute_whatsapp_conversation_ids(self):
        """Deliberately NOT @depends('phone')/@depends('mobile') etc: since
        the real field name isn't confirmed yet, depending on a guessed
        name would either fail install (if it doesn't exist) or silently
        never invalidate correctly (if it's the wrong one anyway). An
        empty @depends() computes once per record load and is refreshed
        by the explicit 'Refresh WhatsApp' button on the form - safe
        either way, and trivial to tighten once the real field is
        confirmed."""
        Contact = self.env["otm.whatsapp.contact"]
        for lead in self:
            conversations = self.env["otm.whatsapp.conversation"]
            phone = lead._get_lead_phone()
            if phone:
                normalized = Contact.normalize_phone(phone)
                contacts = Contact.search([("normalized_phone", "=", normalized)])
                conversations = contacts.mapped("conversation_ids")
            lead.whatsapp_conversation_ids = conversations
            lead.whatsapp_conversation_count = len(conversations)

    def action_refresh_whatsapp(self):
        self._compute_whatsapp_conversation_ids()
        return True

    def action_open_whatsapp(self):
        self.ensure_one()
        phone = self._get_lead_phone()
        if not phone:
            return False
        conversations = self.env["otm.whatsapp.contact"].search(
            [("normalized_phone", "=", self.env["otm.whatsapp.contact"].normalize_phone(phone))]
        ).mapped("conversation_ids")
        return {
            "type": "ir.actions.act_window",
            "name": "WhatsApp",
            "res_model": "otm.whatsapp.conversation",
            "view_mode": "list,form",
            "domain": [("id", "in", conversations.ids)],
            "context": {"default_lead_phone": phone},
        }
