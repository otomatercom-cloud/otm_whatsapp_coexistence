# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OtmWhatsappMessage(models.Model):
    _name = "otm.whatsapp.message"
    _description = "WhatsApp Message"
    _order = "create_date desc"
    _rec_name = "meta_message_id"

    company_id = fields.Many2one(related="phone_id.company_id", store=True, index=True)

    phone_id = fields.Many2one(
        "otm.whatsapp.phone", string="WhatsApp Number", required=True, index=True,
        ondelete="restrict",
    )
    conversation_id = fields.Many2one(
        "otm.whatsapp.conversation", string="Conversation", required=True, index=True,
        ondelete="cascade",
    )
    contact_id = fields.Many2one(
        related="conversation_id.contact_id", store=True, readonly=True, index=True
    )

    direction = fields.Selection(
        [("in", "Incoming"), ("out", "Outgoing")], required=True, index=True
    )
    message_type = fields.Selection(
        [
            ("text", "Text"),
            ("image", "Image"),
            ("video", "Video"),
            ("audio", "Audio"),
            ("document", "Document"),
            ("template", "Template"),
            ("interactive", "Interactive"),
            ("location", "Location"),
            ("sticker", "Sticker"),
            ("other", "Other"),
        ],
        default="text",
        required=True,
    )
    body = fields.Text()

    meta_message_id = fields.Char(
        string="Meta Message ID", index=True,
        help="Meta's wamid - used for idempotent webhook processing and status updates.",
    )

    state = fields.Selection(
        [
            ("received", "Received"),
            ("queued", "Queued"),
            ("sent", "Sent"),
            ("delivered", "Delivered"),
            ("read", "Read"),
            ("failed", "Failed"),
        ],
        default="queued",
        index=True,
    )
    error_code = fields.Char()
    error_message = fields.Text()
    retry_count = fields.Integer(default=0)

    sent_at = fields.Datetime()
    delivered_at = fields.Datetime()
    read_at = fields.Datetime()
    failed_at = fields.Datetime()

    template_id = fields.Many2one("otm.whatsapp.template", string="Template")
    template_variables_json = fields.Text(
        string="Template Variables (JSON)",
        help="Outgoing template messages only: JSON list of ordered values for the "
        "template's {{1}}, {{2}}, ... body placeholders, e.g. [\"John\", \"INV-102\"]. "
        "Leave empty for a template with no variables.",
    )
    template_header_param = fields.Char(
        string="Template Header Value",
        help="Value for a template whose header component itself has a {{1}} "
        "placeholder. Leave empty otherwise.",
    )
    media_id = fields.Many2one("otm.whatsapp.media", string="Media")
    reply_to_id = fields.Many2one("otm.whatsapp.message", string="Reply To")

    # --- Interactive (button/list) message support ---
    # Structured fields rather than a single JSON blob so a chatbot flow
    # node (or any other caller) can set them individually without hand-
    # building Meta's payload shape itself. _build_interactive_payload()
    # is the single place that shape lives.
    interactive_kind = fields.Selection(
        [("button", "Reply Buttons"), ("list", "List Menu")],
        string="Interactive Kind",
        help="Outgoing interactive messages (message_type='interactive') only.",
    )
    interactive_header = fields.Char(string="Interactive Header")
    interactive_footer = fields.Char(string="Interactive Footer")
    interactive_buttons_json = fields.Text(
        string="Buttons (JSON)",
        help="Outgoing button messages: JSON list of up to 3 {\"id\": ..., \"title\": ...} "
        "objects, e.g. [{\"id\": \"opt_a\", \"title\": \"Option A\"}].",
    )
    interactive_list_button_text = fields.Char(
        string="List Button Text",
        help="The text on the button that opens the list picker, e.g. 'View Menu'.",
    )
    interactive_sections_json = fields.Text(
        string="Sections (JSON)",
        help="Outgoing list messages: JSON list of {\"title\": ..., \"rows\": [{\"id\", "
        "\"title\", \"description\"}]} sections, per Meta's list-message shape.",
    )
    # Populated on INCOMING interactive replies (a customer tapping a
    # button or picking a list row) - the raw id you defined when sending,
    # so calling code (e.g. a chatbot flow) can branch on it without
    # re-parsing `body`.
    interactive_reply_id = fields.Char(string="Interactive Reply ID", readonly=True)
    user_id = fields.Many2one(
        "res.users", string="Sent By", default=lambda self: self.env.user
    )

    _meta_message_id_uniq = models.Constraint(
        "unique(meta_message_id)",
        "This Meta message has already been recorded (duplicate webhook/send).",
    )

    MAX_RETRY = 5
    # Meta error codes considered permanent (no benefit retrying)
    PERMANENT_ERROR_CODES = {
        "131026",  # message undeliverable
        "131047",  # re-engagement / 24h window
        "131051",  # unsupported message type
        "132000",  # template does not exist / not approved
        "131009",  # parameter format mismatch
        "100",  # invalid parameter
    }

    # ------------------------------------------------------------------
    # Inbound (webhook -> message)
    # ------------------------------------------------------------------
    @api.model
    def process_inbound(self, phone, wa_message, contact):
        """Idempotently create an inbound message from a parsed Meta webhook
        message payload. `phone` is an otm.whatsapp.phone recordset (1),
        `contact` an otm.whatsapp.contact recordset (1).
        """
        meta_id = wa_message.get("id")
        if meta_id:
            existing = self.search([("meta_message_id", "=", meta_id)], limit=1)
            if existing:
                _logger.info("Ignoring duplicate inbound WhatsApp webhook message %s", meta_id)
                return existing

        conversation = self.env["otm.whatsapp.conversation"].get_or_create(
            phone.id, contact.id
        )
        msg_type = wa_message.get("type", "text")
        body = ""
        interactive_reply_id = False
        if msg_type == "text":
            body = wa_message.get("text", {}).get("body", "")
        elif msg_type in ("image", "video", "audio", "document", "sticker"):
            body = wa_message.get(msg_type, {}).get("caption", "") or "[%s]" % msg_type
        elif msg_type == "location":
            loc = wa_message.get("location", {})
            body = "Location: %s, %s" % (loc.get("latitude"), loc.get("longitude"))
        elif msg_type == "interactive":
            # A customer tapped a reply button or picked a list row - shapes
            # verified against Meta's real webhook reference
            # (developers.facebook.com/documentation/business-messaging/
            # whatsapp/webhooks/reference/messages/interactive):
            # {"interactive": {"type": "button_reply", "button_reply":
            #  {"id": ..., "title": ...}}} or the "list_reply" sibling.
            interactive = wa_message.get("interactive", {})
            reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
            body = reply.get("title") or "[interactive reply]"
            interactive_reply_id = reply.get("id") or False
        else:
            body = "[%s]" % msg_type

        message = self.create(
            {
                "phone_id": phone.id,
                "conversation_id": conversation.id,
                "direction": "in",
                "message_type": msg_type if msg_type in dict(self._fields["message_type"].selection) else "other",
                "body": body,
                "meta_message_id": meta_id,
                "state": "received",
                "interactive_reply_id": interactive_reply_id,
            }
        )
        conversation.write(
            {
                "last_message": body,
                "last_message_date": fields.Datetime.now(),
                "unread_count": conversation.unread_count + 1,
            }
        )
        phone.write({"last_webhook": fields.Datetime.now()})
        return message

    @api.model
    def process_status_update(self, status):
        """Idempotently apply a Meta message-status webhook event
        (sent/delivered/read/failed) to the matching outbound message."""
        meta_id = status.get("id")
        if not meta_id:
            return False
        message = self.search([("meta_message_id", "=", meta_id)], limit=1)
        if not message:
            _logger.info("Status update for unknown WhatsApp message %s - ignored", meta_id)
            return False
        new_state = status.get("status")
        vals = {}
        now = fields.Datetime.now()
        if new_state == "sent":
            vals = {"state": "sent", "sent_at": now}
        elif new_state == "delivered":
            vals = {"state": "delivered", "delivered_at": now}
        elif new_state == "read":
            vals = {"state": "read", "read_at": now}
        elif new_state == "failed":
            errors = status.get("errors") or [{}]
            err = errors[0]
            vals = {
                "state": "failed",
                "failed_at": now,
                "error_code": str(err.get("code", "")),
                "error_message": err.get("title") or err.get("message") or "",
            }
        elif new_state:
            # Safe by construction (vals stays empty, nothing is written) -
            # but logged so a new Meta status value (e.g. "deleted",
            # "warning") is visible instead of silently dropped, matching
            # the observability added for the coexistence_status /
            # template category+status mapping fixes.
            _logger.info("WhatsApp: unhandled message status value %r - no state change applied", new_state)
        # Never regress a message backward (e.g. a late "sent" arriving after "read")
        state_order = ["queued", "sent", "delivered", "read", "failed"]
        if vals and (
            message.state not in state_order
            or state_order.index(vals.get("state", message.state))
            >= state_order.index(message.state)
        ):
            message.write(vals)
        return message

    # ------------------------------------------------------------------
    # Outbound (queue -> Meta)
    # ------------------------------------------------------------------
    def action_send_now(self):
        for message in self:
            message._send()

    def _send(self):
        self.ensure_one()
        if self.direction != "out":
            raise UserError("Only outgoing messages can be sent.")
        client = self.phone_id.get_client()
        try:
            if self.message_type == "template" and self.template_id:
                body_params = None
                if self.template_variables_json:
                    try:
                        body_params = json.loads(self.template_variables_json)
                    except (ValueError, TypeError):
                        body_params = None
                result = client.send_template(
                    self.phone_id,
                    self.conversation_id.contact_id.phone,
                    self.template_id,
                    body_params=body_params,
                    header_param=self.template_header_param or None,
                )
            elif self.message_type in ("image", "video", "audio", "document") and self.media_id:
                result = client.send_media(
                    self.phone_id,
                    self.conversation_id.contact_id.phone,
                    self.message_type,
                    self.media_id,
                    caption=self.body,
                )
            elif self.message_type == "interactive" and self.interactive_kind:
                result = self._send_interactive(client)
            else:
                result = client.send_text(
                    self.phone_id, self.conversation_id.contact_id.phone, self.body or ""
                )
        except Exception as exc:  # noqa: BLE001 - surfaced onto the queue record
            self._mark_failed(str(exc))
            return False

        if result.get("error"):
            self._mark_failed(
                result["error"].get("message", "Unknown error"),
                code=str(result["error"].get("code", "")),
            )
            return False

        meta_id = (result.get("messages") or [{}])[0].get("id")
        self.write(
            {
                "meta_message_id": meta_id,
                "state": "sent",
                "sent_at": fields.Datetime.now(),
                "error_code": False,
                "error_message": False,
            }
        )
        self.conversation_id.write(
            {"last_message": self.body or "[%s]" % self.message_type, "last_message_date": fields.Datetime.now()}
        )
        return True

    def _send_interactive(self, client):
        """Parses interactive_buttons_json / interactive_sections_json and
        dispatches to the matching Meta client method. JSON parsing errors
        are returned in the same {"error": {...}} shape _send() already
        expects from the Meta client, so a malformed payload fails the
        message cleanly (queue/retry as normal) instead of raising past
        the try/except in _send()."""
        self.ensure_one()
        to = self.conversation_id.contact_id.phone
        if self.interactive_kind == "button":
            try:
                buttons = json.loads(self.interactive_buttons_json or "[]")
            except (ValueError, TypeError):
                return {"error": {"message": "interactive_buttons_json is not valid JSON"}}
            if not buttons:
                return {"error": {"message": "No buttons configured for this interactive message"}}
            return client.send_interactive_buttons(
                self.phone_id, to, self.body or "", buttons,
                header=self.interactive_header or None, footer=self.interactive_footer or None,
            )
        if self.interactive_kind == "list":
            try:
                sections = json.loads(self.interactive_sections_json or "[]")
            except (ValueError, TypeError):
                return {"error": {"message": "interactive_sections_json is not valid JSON"}}
            if not sections:
                return {"error": {"message": "No sections configured for this interactive message"}}
            return client.send_interactive_list(
                self.phone_id, to, self.body or "", self.interactive_list_button_text or "Choose",
                sections, header=self.interactive_header or None, footer=self.interactive_footer or None,
            )
        return {"error": {"message": "Unknown interactive_kind %r" % self.interactive_kind}}

    def _mark_failed(self, error_message, code=False):
        self.write(
            {
                "state": "failed",
                "failed_at": fields.Datetime.now(),
                "error_message": error_message,
                "error_code": code or self.error_code,
            }
        )

    def action_retry(self):
        for message in self:
            if message.error_code in message.PERMANENT_ERROR_CODES:
                continue
            if message.retry_count >= message.MAX_RETRY:
                continue
            message.write({"retry_count": message.retry_count + 1, "state": "queued"})
            message._send()

    @api.model
    def _cron_process_queue(self):
        """Cron entry point (delegate pattern) - processes queued outgoing
        messages and retries failed ones that are not permanently failed."""
        queued = self.search([("direction", "=", "out"), ("state", "=", "queued")], limit=200)
        for message in queued:
            message._send()

        retryable = self.search(
            [
                ("direction", "=", "out"),
                ("state", "=", "failed"),
                ("retry_count", "<", self.MAX_RETRY),
            ],
            limit=200,
        )
        for message in retryable:
            if message.error_code in message.PERMANENT_ERROR_CODES:
                continue
            message.write({"retry_count": message.retry_count + 1})
            message._send()
