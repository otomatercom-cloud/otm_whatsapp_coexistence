# -*- coding: utf-8 -*-
{
    "name": "Otomater WhatsApp Multi-Number Coexistence",
    "version": "19.0.1.0.0",
    "category": "Customizations",
    "summary": "One Meta WhatsApp Business Platform integration, multiple WhatsApp numbers, unified Odoo inbox",
    "description": """
Otomater WhatsApp Multi-Number Coexistence
===========================================
Connects ONE Meta WhatsApp Business Platform (Cloud API) integration to
Odoo 19 and exposes MULTIPLE WhatsApp Business phone numbers (each backed
by Meta's official Coexistence / Cloud API mechanism) inside a single,
unified Odoo Inbox.

* Official Meta Cloud API only - no WhatsApp Web automation of any kind.
* One WABA (WhatsApp Business Account) integration record can host many
  otm.whatsapp.phone records (one per connected mobile number).
* Webhook events are routed to the correct number via Meta's
  phone_number_id, never a default/fallback number.
* Per-number team/user assignment with record-rule based access control.
* CRM, Student, Admission and Fee integration hooks (only wired to models
  that actually exist in the target database - see README).
""",
    "author": "Otomater",
    "website": "https://otomater.com",
    "license": "OPL-1",
    "depends": ["base", "mail", "web", "custom_leads_19"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/whatsapp_security_groups.xml",
        "security/ir.model.access.csv",
        "security/whatsapp_security_rules.xml",
        "data/ir_cron_data.xml",
        "data/ir_sequence_data.xml",
        "views/whatsapp_contact_views.xml",
        "views/whatsapp_template_views.xml",
        "views/whatsapp_message_views.xml",
        "views/whatsapp_conversation_views.xml",
        "views/whatsapp_phone_views.xml",
        "views/whatsapp_integration_views.xml",
        "views/whatsapp_inbox_views.xml",
        "views/leads_logic_views.xml",
        "views/whatsapp_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "otm_whatsapp_coexistence/static/src/components/whatsapp_inbox/whatsapp_inbox.js",
            "otm_whatsapp_coexistence/static/src/components/whatsapp_inbox/whatsapp_inbox.xml",
            "otm_whatsapp_coexistence/static/src/components/whatsapp_inbox/whatsapp_inbox.css",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
