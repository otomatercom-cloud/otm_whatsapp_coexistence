# -*- coding: utf-8 -*-
"""Thin, explicit wrapper around the official Meta WhatsApp Business Cloud API
(Graph API). No unofficial WhatsApp Web automation of any kind - only the
documented https://graph.facebook.com/<version>/... REST endpoints.

The client always knows which otm.whatsapp.phone it is acting for; it never
hard-codes a phone id or token - both come from the integration/phone
records passed in.
"""
import logging

import requests

_logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"
TIMEOUT = 20


class MetaWhatsappClient:
    def __init__(self, integration):
        """`integration` is an otm.whatsapp.integration recordset of 1."""
        self.integration = integration
        self.version = integration.graph_api_version or "v21.0"
        self.token = integration.sudo().access_token

    # ------------------------------------------------------------------
    # low-level HTTP helpers
    # ------------------------------------------------------------------
    def _url(self, path):
        return "%s/%s/%s" % (GRAPH_BASE, self.version, path)

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"}

    def _get(self, path, params=None):
        resp = requests.get(self._url(path), headers=self._headers(), params=params or {}, timeout=TIMEOUT)
        return self._parse(resp)

    def _post(self, path, payload):
        resp = requests.post(self._url(path), headers=self._headers(), json=payload, timeout=TIMEOUT)
        return self._parse(resp)

    def _post_multipart(self, path, files, data):
        headers = {"Authorization": "Bearer %s" % self.token}
        resp = requests.post(self._url(path), headers=headers, files=files, data=data, timeout=TIMEOUT)
        return self._parse(resp)

    @staticmethod
    def _parse(resp):
        try:
            data = resp.json()
        except ValueError:
            return {"error": {"message": "Non-JSON response (HTTP %s)" % resp.status_code}}
        if resp.status_code >= 400 and "error" not in data:
            data["error"] = {"message": "HTTP %s" % resp.status_code}
        return data

    # ------------------------------------------------------------------
    # connection / discovery
    # ------------------------------------------------------------------
    def check_connection(self):
        result = self._get(self.integration.business_account_id)
        if result.get("error"):
            return False, result["error"].get("message", "Unknown connection error")
        return True, "Connected"

    def get_phone_numbers(self):
        """List phone numbers registered under the integration's WABA."""
        result = self._get(
            "%s/phone_numbers" % self.integration.business_account_id,
            params={
                "fields": "id,display_phone_number,verified_name,quality_rating,"
                "code_verification_status,platform_type,is_official_business_account"
            },
        )
        if result.get("error"):
            _logger.error("WhatsApp get_phone_numbers failed: %s", result["error"])
            return []
        return result.get("data", [])

    def get_templates(self):
        result = self._get(
            "%s/message_templates" % self.integration.business_account_id,
            params={"fields": "name,language,status,category,components,id", "limit": 200},
        )
        if result.get("error"):
            _logger.error("WhatsApp get_templates failed: %s", result["error"])
            return []
        return result.get("data", [])

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------
    def send_text(self, phone, to, body):
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        return self._post("%s/messages" % phone.phone_number_id, payload)

    def send_template(self, phone, to, template):
        import json

        try:
            components = json.loads(template.components_json.replace("'", '"')) if template.components_json else []
        except Exception:  # noqa: BLE001
            components = []
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template.template_name,
                "language": {"code": template.language},
                "components": components,
            },
        }
        return self._post("%s/messages" % phone.phone_number_id, payload)

    def send_media(self, phone, to, media_type, media, caption=False):
        media_payload = {"id": media.meta_media_id} if media.meta_media_id else {}
        if caption and media_type in ("image", "video", "document"):
            media_payload["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": media_type,
            media_type: media_payload,
        }
        return self._post("%s/messages" % phone.phone_number_id, payload)

    def send_interactive_buttons(self, phone, to, body, buttons, header=None, footer=None):
        """`buttons`: list of {"id": str, "title": str}, max 3 - Meta hard caps
        both the count and each title at 20 characters; verified against
        developers.facebook.com/documentation/business-messaging/whatsapp/
        messages/interactive-reply-buttons-messages."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
                        for b in buttons[:3]
                    ]
                },
            },
        }
        if header:
            payload["interactive"]["header"] = {"type": "text", "text": header}
        if footer:
            payload["interactive"]["footer"] = {"text": footer}
        return self._post("%s/messages" % phone.phone_number_id, payload)

    def send_interactive_list(self, phone, to, body, button_text, sections, header=None, footer=None):
        """`sections`: list of {"title": str, "rows": [{"id","title","description"}]} -
        Meta caps at 10 sections and 10 rows total across all sections combined;
        verified against developers.facebook.com/documentation/business-
        messaging/whatsapp/messages/interactive-list-messages."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": {"button": button_text[:20], "sections": sections},
            },
        }
        if header:
            payload["interactive"]["header"] = {"type": "text", "text": header}
        if footer:
            payload["interactive"]["footer"] = {"text": footer}
        return self._post("%s/messages" % phone.phone_number_id, payload)

    def upload_media(self, phone, file_content, mime_type, filename):
        files = {"file": (filename, file_content, mime_type)}
        data = {"messaging_product": "whatsapp"}
        return self._post_multipart("%s/media" % phone.phone_number_id, files, data)

    def get_media_url(self, media_id):
        return self._get(media_id)

    def download_media(self, media_url):
        resp = requests.get(media_url, headers=self._headers(), timeout=TIMEOUT)
        return resp.content, resp.headers.get("Content-Type")
