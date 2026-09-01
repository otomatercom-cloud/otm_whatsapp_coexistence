# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsappWebhookController(http.Controller):
    """Official Meta Cloud API webhook receiver.

    Routes every event to the correct otm.whatsapp.phone via Meta's
    metadata.phone_number_id - never a default/fallback number (spec
    section 10/11). Fast to acknowledge (returns 200 quickly), idempotent
    (delegates to the message model's dedup-by-meta_message_id logic).
    """

    @http.route("/webhook/whatsapp", type="http", auth="public", methods=["GET"], csrf=False)
    def verify(self, **kwargs):
        mode = kwargs.get("hub.mode")
        token = kwargs.get("hub.verify_token")
        challenge = kwargs.get("hub.challenge", "")

        integration = request.env["otm.whatsapp.integration"].sudo().search(
            [("webhook_verify_token", "=", token)], limit=1
        )
        if mode == "subscribe" and token and integration:
            return request.make_response(challenge)
        _logger.warning("WhatsApp webhook verification failed (mode=%s)", mode)
        return request.make_response("Forbidden", status=403)

    @http.route("/webhook/whatsapp", type="http", auth="public", methods=["POST"], csrf=False)
    def receive(self, **kwargs):
        raw_body = request.httprequest.data
        if not self._verify_signature(raw_body):
            _logger.warning("WhatsApp webhook: invalid signature - rejected")
            return request.make_response("Forbidden", status=403)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            _logger.warning("WhatsApp webhook: malformed JSON payload")
            return request.make_response("OK", status=200)

        try:
            self._process_payload(payload)
        except Exception:  # noqa: BLE001 - never let a processing bug break Meta's retry cadence
            _logger.exception("WhatsApp webhook processing failed")
        # Always ack 200 quickly so Meta doesn't retry-storm us; failures are logged.
        return request.make_response("OK", status=200)

    # ------------------------------------------------------------------
    def _verify_signature(self, raw_body):
        """Validate X-Hub-Signature-256 against any configured app secret.
        If no integration has an app_secret configured, skip (documented
        as a config gap, not silently insecure-by-default in a way that
        blocks first-time setup)."""
        integrations = request.env["otm.whatsapp.integration"].sudo().search(
            [("app_secret", "!=", False)]
        )
        if not integrations:
            return True
        signature = request.httprequest.headers.get("X-Hub-Signature-256", "")
        if not signature.startswith("sha256="):
            return False
        provided = signature.split("=", 1)[1]
        for integration in integrations:
            expected = hmac.new(
                integration.app_secret.encode(), raw_body, hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(expected, provided):
                return True
        return False

    def _process_payload(self, payload):
        Phone = request.env["otm.whatsapp.phone"].sudo()
        Contact = request.env["otm.whatsapp.contact"].sudo()
        Message = request.env["otm.whatsapp.message"].sudo()

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id")
                if not phone_number_id:
                    continue

                phone = Phone.search([("phone_number_id", "=", phone_number_id)], limit=1)
                if not phone:
                    _logger.warning(
                        "WhatsApp webhook: unknown phone_number_id %s - event dropped",
                        phone_number_id,
                    )
                    continue

                for wa_message in value.get("messages", []):
                    contact_data = self._extract_contact(value, wa_message.get("from"))
                    contact = Contact.get_or_create_from_wa(
                        wa_message.get("from"), wa_message.get("from"), contact_data.get("profile_name")
                    )
                    Message.process_inbound(phone, wa_message, contact)

                for status in value.get("statuses", []):
                    Message.process_status_update(status)

    @staticmethod
    def _extract_contact(value, wa_id):
        for contact in value.get("contacts", []):
            if contact.get("wa_id") == wa_id:
                return {"profile_name": contact.get("profile", {}).get("name")}
        return {}
