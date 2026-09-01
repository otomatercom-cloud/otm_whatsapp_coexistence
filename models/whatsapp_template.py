# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class OtmWhatsappTemplate(models.Model):
    _name = "otm.whatsapp.template"
    _description = "WhatsApp Message Template"
    _rec_name = "template_name"

    integration_id = fields.Many2one(
        "otm.whatsapp.integration", string="Meta Integration", required=True, index=True,
        ondelete="cascade",
    )
    template_name = fields.Char(string="Template Name", required=True, index=True)
    language = fields.Char(default="en_US", required=True)
    category = fields.Selection(
        [
            ("marketing", "Marketing"),
            ("utility", "Utility"),
            ("authentication", "Authentication"),
            ("other", "Other (see raw category)"),
        ],
        default="utility",
    )
    status = fields.Selection(
        [
            ("approved", "Approved"),
            ("pending", "Pending"),
            ("rejected", "Rejected"),
            ("disabled", "Disabled"),
            ("paused", "Paused"),
            ("in_appeal", "In Appeal"),
            ("pending_deletion", "Pending Deletion"),
            ("other", "Other (see raw status)"),
        ],
        default="pending",
    )
    raw_category = fields.Char(
        string="Raw Meta Category",
        help="Meta's exact category string as returned by the API - kept alongside the "
        "mapped `category` selection so an unmapped/new Meta value is never silently "
        "lost, only the selection falls back to 'other'.",
    )
    raw_status = fields.Char(
        string="Raw Meta Status",
        help="Meta's exact status string as returned by the API - same reasoning as "
        "raw_category. Meta has more template statuses than this module's Selection "
        "enumerates (e.g. LIMIT_EXCEEDED, PENDING_TEMPLATE_QUALITY) - an unmapped one "
        "maps to 'other' here rather than crashing the sync.",
    )
    meta_template_id = fields.Char(string="Meta Template ID", index=True)
    components_json = fields.Text(
        string="Components (JSON)", help="Raw Meta template component structure."
    )
    variable_count = fields.Integer(string="Body Variables")
    has_buttons = fields.Boolean()
    active = fields.Boolean(default=True)

    _template_uniq = models.Constraint(
        "unique(integration_id, template_name, language)",
        "This template name/language already exists for this integration.",
    )

    _CATEGORY_MAP = {
        "MARKETING": "marketing",
        "UTILITY": "utility",
        "AUTHENTICATION": "authentication",
    }
    _STATUS_MAP = {
        "APPROVED": "approved",
        "PENDING": "pending",
        "REJECTED": "rejected",
        "DISABLED": "disabled",
        "PAUSED": "paused",
        "IN_APPEAL": "in_appeal",
        "PENDING_DELETION": "pending_deletion",
    }

    @api.model
    def _map_category(self, raw):
        """Never raises on an unrecognized Meta category - see raw_category
        note above. Same reasoning/fix as
        whatsapp_integration.py._map_coexistence_status (real production
        crash: `otm.whatsapp.phone.coexistence_status: 'NOT_VERIFIED'` from
        writing an unmapped raw Meta enum straight into a Selection field -
        proactively swept this same pattern here too)."""
        if not raw:
            return "utility"
        mapped = self._CATEGORY_MAP.get(raw.upper())
        if mapped:
            return mapped
        _logger.warning(
            "WhatsApp: unmapped Meta template category %r - defaulting to 'other'. "
            "Add a mapping in whatsapp_template.py._CATEGORY_MAP.", raw,
        )
        return "other"

    @api.model
    def _map_status(self, raw):
        if not raw:
            return "pending"
        mapped = self._STATUS_MAP.get(raw.upper())
        if mapped:
            return mapped
        _logger.warning(
            "WhatsApp: unmapped Meta template status %r - defaulting to 'other'. "
            "Add a mapping in whatsapp_template.py._STATUS_MAP.", raw,
        )
        return "other"

    def action_sync_templates(self):
        """Delegates to otm.whatsapp.integration._sync_templates() so there is
        exactly one code path for template syncing (also used by the daily
        cron) - never duplicated logic."""
        for integration in self.mapped("integration_id"):
            integration._sync_templates()
        return True
