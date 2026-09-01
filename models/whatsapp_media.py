# -*- coding: utf-8 -*-
from odoo import fields, models


class OtmWhatsappMedia(models.Model):
    """Stores the Meta media id + a local ir.attachment. Never exposes Meta's
    insecure temporary CDN URLs to the frontend - the attachment is the only
    thing ever linked from views/portal."""

    _name = "otm.whatsapp.media"
    _description = "WhatsApp Media"

    meta_media_id = fields.Char(string="Meta Media ID", index=True)
    mime_type = fields.Char()
    media_type = fields.Selection(
        [("image", "Image"), ("video", "Video"), ("audio", "Audio"), ("document", "Document")]
    )
    attachment_id = fields.Many2one("ir.attachment", string="Attachment", ondelete="cascade")
    file_size = fields.Integer()
