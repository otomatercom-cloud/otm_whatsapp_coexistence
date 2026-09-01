# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class WhatsappInboxController(http.Controller):
    """Kept thin on purpose: the OWL Inbox widget primarily calls ORM
    methods via `orm.call()` (see whatsapp_inbox.js), which is the
    standard/secure Odoo 19 pattern and already goes through normal
    ir.rule / ir.model.access enforcement. This controller only exists
    for the one thing that's awkward over ORM: coercing a browser-sent
    id. Every id coming from the client is explicitly int()-coerced
    before any .browse() call (erp-tooling finding #20)."""

    @http.route("/whatsapp/inbox/select_phone", type="jsonrpc", auth="user")
    def select_phone(self, phone_id=None):
        try:
            phone_id = int(phone_id) if phone_id else False
        except (TypeError, ValueError):
            phone_id = False
        domain = [("id", "=", phone_id)] if phone_id else []
        phones = request.env["otm.whatsapp.phone"].search(domain)
        return {"phone_ids": phones.ids}
