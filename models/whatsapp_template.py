# -*- coding: utf-8 -*-
from odoo import fields, models


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
        ],
        default="utility",
    )
    status = fields.Selection(
        [
            ("approved", "Approved"),
            ("pending", "Pending"),
            ("rejected", "Rejected"),
            ("disabled", "Disabled"),
        ],
        default="pending",
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

    def action_sync_templates(self):
        """Delegates to otm.whatsapp.integration._sync_templates() so there is
        exactly one code path for template syncing (also used by the daily
        cron) - never duplicated logic."""
        for integration in self.mapped("integration_id"):
            integration._sync_templates()
        return True
