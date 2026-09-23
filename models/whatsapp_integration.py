# -*- coding: utf-8 -*-
import json
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
            components = tpl.get("components") or []
            variable_count, has_buttons = Template._parse_components_meta(components)
            vals = {
                "integration_id": self.id,
                "template_name": tpl.get("name"),
                "language": tpl.get("language"),
                "category": Template._map_category(tpl.get("category")),
                "status": Template._map_status(tpl.get("status")),
                "raw_category": tpl.get("category") or False,
                "raw_status": tpl.get("status") or False,
                "meta_template_id": tpl.get("id"),
                # FIX: store real JSON (json.dumps), not Python's str(list) -
                # the old str() output wasn't valid JSON at all (single
                # quotes, "True"/"None") and was also the wrong shape to
                # ever resend as-is (see meta_whatsapp_client.send_template).
                # Kept purely for display/reference now.
                "components_json": json.dumps(components),
                "variable_count": variable_count,
                "has_buttons": has_buttons,
            }
            if existing:
                existing.write(vals)
            else:
                Template.create(vals)

    # Meta's phone-numbers API returns `code_verification_status` as one of
    # a small set of UPPERCASE enum strings (VERIFIED / NOT_VERIFIED /
    # EXPIRED) - these do NOT match our own coexistence_status Selection
    # values and writing them in raw crashes with
    # `ValueError: Wrong value for otm.whatsapp.phone.coexistence_status`
    # (confirmed against a real production sync against a live WABA -
    # NOT_VERIFIED was the value that crashed). Fixed by mapping through an
    # explicit table with a safe, never-crashing fallback instead of
    # passing Meta's raw string straight into the Selection field.
    _META_VERIFICATION_STATUS_MAP = {
        "VERIFIED": "platform_only",
        "NOT_VERIFIED": "pending",
        "EXPIRED": "error",
    }

    def _map_coexistence_status(self, num):
        """Never raises, never writes an unmapped raw Meta value into the
        Selection field - unmapped values log a warning (so a new Meta enum
        value shows up in the logs immediately, not as a crashed sync) and
        fall back to 'pending' rather than failing the whole batch."""
        if num.get("platform_type") == "CLOUD_API" or num.get("is_official_business_account"):
            return "enabled"
        raw = num.get("code_verification_status")
        mapped = self._META_VERIFICATION_STATUS_MAP.get(raw)
        if mapped:
            return mapped
        if raw:
            _logger.warning(
                "WhatsApp: unmapped Meta code_verification_status %r for a synced "
                "phone number - defaulting coexistence_status to 'pending'. Add a "
                "mapping in whatsapp_integration.py._META_VERIFICATION_STATUS_MAP.",
                raw,
            )
        return "pending"

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
                    "coexistence_status": rec._map_coexistence_status(num),
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
