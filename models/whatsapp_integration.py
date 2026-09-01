# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OtmWhatsappIntegration(models.Model):
    """One centralized Meta WhatsApp Business Platform integration.

    A single integration record holds the Meta App / WABA credentials.
    Many otm.whatsapp.phone records (one per connected mobile number)
    live under ONE integration - this is the "one API, many numbers"
    architecture required by the spec. A second integration record is
    only ever needed if Meta itself requires a separate Business
    Account / App (different credentials), never just because there is
    another phone number to add.
    """

    _name = "otm.whatsapp.integration"
    _description = "WhatsApp Meta Integration"
    _inherit = ["mail.thread"]
    _rec_name = "name"

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    active = fields.Boolean(default=True)

    # --- Meta credentials (never shown in list/tree views, see views XML) ---
    app_id = fields.Char(string="Meta App ID")
    business_account_id = fields.Char(
        string="WhatsApp Business Account ID (WABA ID)", required=True
    )
    business_id = fields.Char(string="Meta Business ID")
    access_token = fields.Char(
        string="Access Token", groups="otm_whatsapp_coexistence.group_whatsapp_administrator"
    )
    webhook_verify_token = fields.Char(
        string="Webhook Verify Token",
        groups="otm_whatsapp_coexistence.group_whatsapp_administrator",
    )
    app_secret = fields.Char(
        string="App Secret", groups="otm_whatsapp_coexistence.group_whatsapp_administrator"
    )
    graph_api_version = fields.Char(default="v21.0", required=True)

    connection_state = fields.Selection(
        [
            ("not_connected", "Not Connected"),
            ("connected", "Connected"),
            ("error", "Error"),
        ],
        default="not_connected",
        tracking=True,
    )
    last_check = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    phone_ids = fields.One2many("otm.whatsapp.phone", "integration_id", string="Phone Numbers")
    phone_count = fields.Integer(compute="_compute_phone_count", string="Number of Phones")

    _waba_uniq = models.Constraint(
        "unique(business_account_id, company_id)",
        "A WhatsApp integration already exists for this WABA ID in this company.",
    )

    @api.depends("phone_ids")
    def _compute_phone_count(self):
        for rec in self:
            rec.phone_count = len(rec.phone_ids)

    def _get_client(self):
        """Return a configured Meta Graph API client service for this integration."""
        self.ensure_one()
        from ..services.meta_whatsapp_client import MetaWhatsappClient

        return MetaWhatsappClient(self)

    def action_check_connection(self):
        for rec in self:
            client = rec._get_client()
            ok, message = client.check_connection()
            rec.write(
                {
                    "connection_state": "connected" if ok else "error",
                    "last_check": fields.Datetime.now(),
                    "last_error": False if ok else message,
                }
            )
            if not ok:
                raise UserError(message)
        return True

    @api.model
    def _cron_sync_templates(self):
        """Cron delegate entry point - syncs templates for every active,
        connected integration by delegating to each integration's own
        _sync_templates() (a single, non-duplicated code path also used
        by the manual 'Sync Templates' button - see whatsapp_template.py)."""
        integrations = self.search([("connection_state", "=", "connected")])
        for integration in integrations:
            integration._sync_templates()

    def _sync_templates(self):
        """Fetch templates from Meta and create/update otm.whatsapp.template
        records for this integration. Matched on (integration, name,
        language) so re-running never duplicates."""
        self.ensure_one()
        client = self._get_client()
        templates = client.get_templates()
        Template = self.env["otm.whatsapp.template"]
        for tpl in templates:
            existing = Template.search(
                [
                    ("integration_id", "=", self.id),
                    ("template_name", "=", tpl.get("name")),
                    ("language", "=", tpl.get("language")),
                ],
                limit=1,
            )
            vals = {
                "integration_id": self.id,
                "template_name": tpl.get("name"),
                "language": tpl.get("language"),
                "category": (tpl.get("category") or "utility").lower(),
                "status": (tpl.get("status") or "pending").lower(),
                "meta_template_id": tpl.get("id"),
                "components_json": str(tpl.get("components")),
            }
            if existing:
                existing.write(vals)
            else:
                Template.create(vals)

    def action_sync_numbers(self):
        """Pull phone numbers from Meta's WABA and create/update otm.whatsapp.phone records.

        Never creates duplicates - matched on phone_number_id.
        """
        Phone = self.env["otm.whatsapp.phone"]
        for rec in self:
            client = rec._get_client()
            numbers = client.get_phone_numbers()
            for num in numbers:
                phone_number_id = num.get("id")
                if not phone_number_id:
                    continue
                existing = Phone.search(
                    [("phone_number_id", "=", phone_number_id)], limit=1
                )
                vals = {
                    "integration_id": rec.id,
                    "phone_number_id": phone_number_id,
                    "display_phone_number": num.get("display_phone_number") or "",
                    "verified_name": num.get("verified_name") or "",
                    "quality_rating": num.get("quality_rating") or "",
                    "coexistence_status": (
                        "enabled"
                        if num.get("platform_type") == "CLOUD_API"
                        or num.get("is_official_business_account")
                        else num.get("code_verification_status", "pending")
                    ),
                    "last_sync": fields.Datetime.now(),
                }
                if existing:
                    existing.write(vals)
                else:
                    vals["name"] = num.get("verified_name") or num.get(
                        "display_phone_number"
                    ) or phone_number_id
                    Phone.create(vals)
        return True
