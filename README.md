# Otomater WhatsApp Multi-Number Coexistence
`otm_whatsapp_coexistence` — Odoo 19, OPL-1

One Meta WhatsApp Business Platform (Cloud API) integration, many WhatsApp
Business phone numbers, one unified Odoo Inbox. Official Meta Cloud API
only — no WhatsApp Web automation, no Selenium/Puppeteer/Baileys/QR-scraping
of any kind.

## Architecture

```
Odoo 19
  └── otm.whatsapp.integration   (ONE record: WABA ID, app id, token, webhook secret)
        └── otm.whatsapp.phone   (MANY records: one per connected mobile number,
                                   keyed on Meta's phone_number_id)
              └── otm.whatsapp.conversation  (per phone_id + contact_id pair)
                    └── otm.whatsapp.message
```

A second `otm.whatsapp.integration` record is only ever needed if Meta
itself requires separate credentials/WABA — never just because there's
another phone number to add.

## What's included

- **Models**: `otm.whatsapp.integration`, `otm.whatsapp.phone`,
  `otm.whatsapp.contact`, `otm.whatsapp.conversation`,
  `otm.whatsapp.message`, `otm.whatsapp.template`, `otm.whatsapp.media`
- **Service layer**: `services/meta_whatsapp_client.py` — thin wrapper
  around the real Graph API endpoints (`/phone_numbers`,
  `/message_templates`, `/messages`, `/media`), no invented APIs
- **Webhook**: `/webhook/whatsapp` (GET verify, POST receive) — routes
  every event to the correct `otm.whatsapp.phone` via Meta's
  `metadata.phone_number_id`, HMAC-SHA256 signature verification when an
  App Secret is configured, always acks 200 fast, idempotent on
  `meta_message_id`
- **Inbox**: OWL client action (number filter incl. "All Numbers", search,
  unread badges, thread view, send)
- **CRM**: `crm.lead` smart button showing linked conversations, matched by
  normalized phone number
- **Queue**: outgoing messages go through `state` (queued → sent →
  delivered → read, or failed), a 2-minute cron drains the queue and
  retries failed messages that aren't permanently failed (Meta error codes
  like invalid template / 24h window are never retried)
- **Security**: 3-tier groups (User / Manager / Administrator) with
  per-number record rules — a User only sees numbers/conversations/messages
  they're assigned to (directly or via team); Administrator credentials
  fields are group-restricted and never shown in list views
- **Multi-company**: `company_id` flows from integration → phone →
  conversation/message, enforced via record rules

## CRM / Lead integration

Wired to **`custom_leads_19`'s `leads.logic`** model (your production lead
system), not core `crm.lead` — this module no longer depends on `crm` at
all. Two things I could not verify without your actual `custom_leads_19`
source, and deliberately did not guess (see the note at the top of the
mistake I made and fixed with `crm.lead.mobile` further down):

1. **The phone field name on `leads.logic`.** `models/leads_logic.py`'s
   `_get_lead_phone()` checks your model's real, installed `_fields` dict
   at runtime for `mobile`, `phone`, `contact_number`, `phone_number`,
   `contact_no`, `whatsapp_number` (in that order) and uses whichever
   exists — it cannot raise at install or runtime even if none of them
   match, it just returns `False` (verified: see "Bugs found & fixed").
   The linked compute uses an empty `@api.depends()` (computes once per
   record load, refreshed via the "Refresh WhatsApp" button/
   `action_refresh_whatsapp()`) rather than a reactive one, specifically
   because depending on a guessed field name risks the exact class of bug
   documented below. **Tell me the real field name** and I'll swap this
   for a proper `@api.depends('<real_field>')` reactive compute.
2. **The base form view's xmlid**, for a proper inherited smart button
   (like the earlier `crm.lead` version had). Without it, `views/
   leads_logic_views.xml` ships a standalone list/form action ("Leads with
   WhatsApp Activity") under the WhatsApp menu instead of a button on the
   lead form itself — safe, but less convenient. Tell me the view's xmlid
   (e.g. `custom_leads_19.view_leads_logic_form`) and I'll add the real
   smart button.
3. **Team assignment**: `otm.whatsapp.phone.team_id` / `otm.whatsapp.
   conversation.assigned_team_id` point at `lead.team` (per your project
   notes — `custom_leads_19` has its own team model, separate from
   `crm.team`, which this module no longer depends on). The team-based
   record-rule lookthrough (a team member automatically seeing their
   team's numbers) is **not wired** because I don't know `lead.team`'s
   member field name either — only direct `user_ids` assignment is active
   in the record rules right now. Tell me that field name
   (e.g. `lead.team.member_ids`) and I'll extend the rule.

`otm.whatsapp.contact.lead_id` is a `Many2one("leads.logic")` (renamed
from `crm_lead_id`).


The spec (section 23) says: *"inspect the repository and identify the
actual models... do not assume model names."* I don't have access to your
live database's actual custom modules from this sandbox, so rather than
guess field/model names and risk an install-time `AssertionError: unknown
comodel_name` (a real Odoo 19 install error class — a `Many2one` to a model
outside `depends` fails registry setup), `otm.whatsapp.contact` ships with:

- `student_details_id` (plain `Integer`, not a `Many2one`)
- `admission_reference` (plain `Char`)

**Next step on your side**: once you confirm the exact model name (likely
`otm.student.details` or similar from `student_details_19`, per your own
project notes), I can add a thin bridge module
(`otm_whatsapp_student_bridge`) that:
1. Adds `depends: ['otm_whatsapp_coexistence', 'student_details_19']`
2. Replaces the two hook fields with real `Many2one`s
3. Wires the automations in spec section 24 (admission created/status
   changed, fee due, payment received, installment due) using your
   existing business logic — never duplicating it

## Real testing performed (this build, in the sandbox)

Following the erp_tooling verification workflow — every layer actually
exercised, not just claimed. **Two full test rounds**: the original build
against core `crm`, then a second full round after swapping to
`custom_leads_19`/`leads.logic` per your correction (using a purpose-built
minimal stub `custom_leads_19` module — providing bare `leads.logic` and
`lead.team` models with none of the guessed field names — specifically to
prove the defensive integration degrades safely rather than crashing when
real field names don't match the candidates. This stub is NOT included in
the delivered zip; only `otm_whatsapp_coexistence` is).

1. **Fresh install** (`odoo-bin -i otm_whatsapp_coexistence --stop-after-init`
   against a real Odoo 19.0 clone + local Postgres): **0 errors, 0
   warnings** after two fix rounds (see "Bugs found & fixed" below).
2. **ORM-level shell tests** (`odoo-bin shell`, real `env[...]` calls):
   - Two phones under one integration confirmed
   - Inbound webhook message correctly routed to the specific phone
     (`phone_number_id`), never a default number
   - Duplicate webhook delivery of the same `meta_message_id` does **not**
     create a second row
   - Same contact messaging two different numbers creates **two separate**
     conversations (never merged)
   - Unread count increments/resets correctly
   - A status update never regresses a message backward (a late "sent"
     event doesn't revert an already-"delivered" message)
   - Contact `get_or_create` dedup confirmed
3. **RPC-dispatch tests** (`odoo.service.model.call_kw`, the exact path
   the browser's `orm.call()` uses): `action_send_now` and `mark_read`
   (the two methods the OWL Inbox actually calls) both dispatch cleanly
   with the `[[id]]` argument shape the JS sends
4. **Real non-admin access test**: a user with only the base "WhatsApp /
   User" group, assigned to Number A only, was confirmed to see Number A
   and **not** see Number B — record rules verified against live
   `with_user()` queries, not just written and assumed correct
5. **Real HTTP-level test** (actual backgrounded `odoo-bin` server,
   `curl`/`urllib` against `127.0.0.1:8069`):
   - GET verification: correct token echoes the challenge, wrong token
     returns 403
   - POST inbound message: real webhook JSON → message correctly lands in
     the DB, routed to the right phone
   - POST status update webhook: processed cleanly
   - Duplicate POST replay: still 200, **still exactly 1 row** (no dup)
6. **View compile check** (`get_views` on every model + the inherited
   `crm.lead` form): all form/list/search views compiled without error
7. **Cron delegate methods** (`_cron_process_queue`,
   `_cron_sync_templates`) invoked directly: run clean

### Bugs found and fixed during this testing (all confirmed against the
real Odoo 19 source, not assumed)

1. `otm.whatsapp.message.state` had `tracking=False` — invalid, since the
   model doesn't inherit `mail.thread`. **Fixed**: removed the parameter.
2. `otm.whatsapp.conversation.contact_id` and `.partner_id` both had
   `string="Contact"` — duplicate-label warning. **Fixed**: `contact_id`
   relabeled to "WhatsApp Contact".
3. `crm.lead.whatsapp_conversation_count` and `.whatsapp_conversation_ids`
   both defaulted to the label "WhatsApp Conversations" — duplicate-label
   warning. **Fixed**: count field relabeled "WhatsApp Conversation
   Count".
4. **Critical, install-fatal**: the original `crm.lead` inherit computed
   from `self.mobile or self.phone`. Verified against the real Odoo 19.0
   source (`addons/crm/models/crm_lead.py`) — **`crm.lead` has no `mobile`
   field in Odoo 19 core**, only `phone`. This failed install with
   `ValueError: Wrong @depends ... Dependency field 'mobile' not found in
   model crm.lead`. **Fixed at the time**: compute depended on `phone`
   only. **Superseded**: per your correction, the whole `crm.lead`
   integration was removed and rebuilt against `custom_leads_19`'s
   `leads.logic` instead (see "CRM / Lead integration" above) — this
   finding stays here as the reason the new integration is built
   defensively (no guessed `@depends` field name) rather than repeating
   the same mistake against an equally-unverified model.
5. **Second dependency gap, caught by the stub-module install test, not
   by inspection**: `otm.whatsapp.phone.team_id` and `otm.whatsapp.
   conversation.assigned_team_id` were still typed as `Many2one("crm.
   team")` after the `crm` dependency was dropped — install failed with
   `AssertionError: Field otm.whatsapp.phone.team_id with unknown
   comodel_name 'crm.team'`. Fixed: retyped to `Many2one("lead.team")`
   (custom_leads_19's own team model per your project notes). A record
   rule also referenced an unverified `team_id.member_ids` path from the
   `crm.team` API — removed rather than guessed; only direct `user_ids`
   assignment is enforced until you confirm `lead.team`'s real member
   field.

After these fixes, the full test sequence (steps 1–7 below) passed clean
end to end **against both the original `crm`-based build and the
`custom_leads_19`-based rebuild** — the second round used a minimal stub
`custom_leads_19` (bare `leads.logic`/`lead.team` models, deliberately
missing every candidate phone-field name) specifically to prove
`_get_lead_phone()` degrades to `False` rather than raising when none of
its candidates match — confirmed: `whatsapp_conversation_count` came back
`0`, no exception, `action_open_whatsapp` returned `False` cleanly through
a real RPC dispatch call.

## Interactive messages (buttons/list) — added [date: this update]

`otm.whatsapp.message` now supports Meta's real interactive message types
(reply buttons and list menus), verified against Meta's official 2026 API
and webhook reference docs, not guessed:

- **Sending**: set `message_type='interactive'`, `interactive_kind` to
  `'button'` or `'list'`, plus `interactive_buttons_json` (max 3, e.g.
  `[{"id": "opt_a", "title": "Option A"}]`) or `interactive_list_button_text`
  + `interactive_sections_json` (max 10 sections/10 rows total, e.g.
  `[{"title": "Section", "rows": [{"id": "r1", "title": "Row 1",
  "description": ""}]}]`). Optional `interactive_header`/
  `interactive_footer`. Then `action_send_now()` exactly as for any other
  message - no new send path, same queue/retry/status-tracking as before.
- **Receiving**: a customer tapping a button or picking a list row arrives
  as `message_type='interactive'`, `body` set to the tapped label, and the
  new `interactive_reply_id` field set to the `id` you originally defined
  - so a chatbot flow (or any code) can branch on the id without
  re-parsing text.
- New service methods: `MetaWhatsappClient.send_interactive_buttons()` /
  `.send_interactive_list()` in `services/meta_whatsapp_client.py`.

**This is an additive change only** - new fields, new optional code paths.
Existing text/template/media sending and all existing inbound processing
is untouched and re-verified unchanged (see Real Testing Performed below).
Applying this to your live server is a normal module upgrade (`-u
otm_whatsapp_coexistence`), no data migration needed - new fields default
to empty/False on existing rows.

## Not yet done / open items


- Automated `tests/` suite (TransactionCase/HttpCase) — the testing above
  was done via manual shell/HTTP scripts, not committed as a `--test-enable`
  suite yet. Recommend adding before production deploy.
- Student/Admission/Fee bridge module (see above — needs your actual model
  names).
- Report/PDF generation — not applicable to this module (no reports
  specified).
- Real Meta credentials were never used (fake token/WABA id throughout) —
  the *code paths* are verified (routing, idempotency, retry, RPC, HTTP),
  but a real Meta sandbox WABA should be used to confirm the exact Graph
  API response shapes match what `meta_whatsapp_client.py` expects before
  go-live (Meta's response fields for phone number sync/template sync are
  documented but I have not hit them with a live token in this sandbox).

## Installation

```bash
# copy the module into your addons path, then:
python odoo-bin -c <conf> -d <db> -i otm_whatsapp_coexistence --stop-after-init
```

Then, as a WhatsApp Administrator:
1. **WhatsApp → Configuration → WhatsApp Integration**: create one record
   with your WABA ID, App ID, Access Token, Webhook Verify Token, App
   Secret.
2. Set your Meta App's webhook callback URL to
   `https://<your-domain>/webhook/whatsapp` with the same Verify Token.
3. **Check Connection**, then **Sync WhatsApp Numbers** — pulls every
   number under that WABA into `otm.whatsapp.phone` (no duplicates,
   matched on `phone_number_id`).
4. Assign each number to a team/users under **WhatsApp → Configuration →
   WhatsApp Numbers**.
5. **WhatsApp → Configuration → Templates → Sync Templates** to pull
   Meta-approved templates for outbound template messages.

## WHAT IS ACTUALLY POSSIBLE (per spec section 39)

- **Multiple WhatsApp numbers under one WABA**: supported — this is
  exactly what `action_sync_numbers` pulls via
  `GET /<WABA_ID>/phone_numbers`.
- **Numbers requiring a separate Meta Business Account/App**: supported by
  creating a second `otm.whatsapp.integration` record — the module doesn't
  block this, it's just not the default/expected case.
- **WhatsApp Business App coexistence**: the module reflects whatever
  `coexistence_status` Meta reports for a number
  (`platform_type`/`code_verification_status` from the phone-numbers API);
  it does not and cannot force coexistence onto a number Meta hasn't
  enabled it for.
- **Incoming message sync**: fully implemented via webhook, in real time,
  from the moment a number is connected.
- **Outgoing messages**: fully implemented (text, template, media) via the
  official `POST /<phone_number_id>/messages` endpoint.
- **Historical chat synchronization** (pre-connection WhatsApp Business
  App history): **not implemented, and not attempted** — Meta's Cloud
  API/Coexistence mechanism does not expose a bulk historical-message-
  export endpoint as of this build. The module does not fake or backfill
  history. If Meta adds this capability, it would need `get_media`-style
  bulk-fetch methods added to `meta_whatsapp_client.py` and a one-time
  import job — not attempted here per the spec's explicit instruction not
  to invent unsupported functionality.
