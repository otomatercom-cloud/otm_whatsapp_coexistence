# Meta WhatsApp Configuration — Step-by-Step Guide
For: `otm_whatsapp_coexistence` (Odoo 19)

This walks through everything on the **Meta side** needed before you fill in
the **WhatsApp → Configuration → WhatsApp Integration** form in Odoo, plus
the exact Odoo-side steps after. Verified against Meta's current (2026)
Cloud API / WhatsApp Business Platform documentation and onboarding flow —
Meta's own screens can shift wording between minor releases, so if a menu
label below doesn't match exactly, look for the nearest equivalent (e.g.
"Business Settings" vs "Business Manager" have been renamed a few times).

---

## Part A — One-time Meta setup

### A1. Create/verify a Meta Business Portfolio
1. Go to **business.facebook.com** and create a Business Portfolio (or use
   your existing one) for Otomater / the client the number belongs to.
2. **Business Settings → Security Center → Business Verification** — upload
   the documents Meta accepts for your country (in India, typically a GST
   certificate or incorporation certificate + a utility bill matching the
   registered business address, dated within ~3 months). Verification
   review commonly takes a few business days.

You can start API setup before verification finishes, but Meta will cap
your messaging tier (very low daily conversation limits) until it's done.

### A2. Create a Meta App with the WhatsApp product
1. Go to **developers.facebook.com → My Apps → Create App**.
2. Choose **Business** as the app type, then select the **WhatsApp** use
   case when prompted.
3. Attach the app to the Business Portfolio from A1.
4. Note the **App ID** shown on the app dashboard — this goes in Odoo's
   integration form as **Meta App ID**.

### A3. Create the WhatsApp Business Account (WABA) and a phone number
In the App Dashboard, go to **WhatsApp → API Setup** (sometimes labeled
**Configuration**). This panel walks you through creating a WABA and
attaching a phone number. There are three distinct paths — **pick the one
that matches your actual number**, this decision is not easily reversible:

| Path | When to use | What happens |
|---|---|---|
| **Create New** | You want a brand-new number dedicated to the API, never used on any phone | Meta issues a fresh number/verifies a new one you provide, no chat history |
| **Use Existing API Number** | The number already lives on Cloud API under a different WABA/partner | Meta migrates it — old webhook stops working, some downtime |
| **Connect a WhatsApp Business App** (**Coexistence**) | You want to keep using the number in the regular WhatsApp Business mobile app **and** add the API on top | See A4 below — this is almost certainly what you want for Anjion/Logic School's existing numbers |

For a genuinely new dedicated number, choose "Create New" and follow the
SMS/voice verification prompt — Meta texts or calls a code, you enter it,
done.

### A4. Coexistence flow (connect an existing WhatsApp Business App number)
This is the path described in the module spec (section 8–9) — the number
keeps working normally in the phone's WhatsApp Business app while Odoo also
receives/sends through the Cloud API.

1. In **WhatsApp → API Setup**, choose the option to **connect an existing
   WhatsApp Business App** rather than "Create New" or "Use Existing API
   Number".
2. Enter the phone number currently active in the WhatsApp Business app on
   the phone.
3. Meta's Embedded Signup shows a **QR code**. On the phone, open the
   **WhatsApp Business app itself** (not a browser) and scan it — keep the
   app open and the phone on Wi-Fi/data during the whole process.
4. You'll be asked whether to **sync existing chat history** — Meta
   currently supports syncing roughly the **last 6 months** of 1:1 chats;
   media older than ~14 days at time of sync won't come across. This is a
   one-time sync at connection time, not an ongoing bulk export — the
   module's README already documents this limitation (spec section 9) and
   nothing in the module fakes or backfills beyond what Meta itself hands
   over here.
5. Once synced, the phone's WhatsApp Business app shows a small indicator
   that the number is now connected to an API integration. New messages
   from that point on flow both ways in real time.
6. **Operational rule for Coexistence numbers**: open the WhatsApp Business
   app on the registered phone at least **once every 14 days**, or Meta
   pauses the API-side link until you reopen it. Worth a calendar reminder
   per connected number.
7. A few WhatsApp Business app features are disabled once Coexistence is
   active on a number: live location sharing and disappearing messages in
   1:1 chats, and broadcast lists become view-only from the app side.
   Nothing else in normal usage changes.

Repeat A3/A4 once per phone number you want under this integration — they
all attach to the **same WABA** unless Meta specifically requires
otherwise, which is exactly the "one integration, many numbers" shape the
module is built around.

### A5. Collect your WABA ID, Business ID
- **WABA ID**: visible in the API Setup panel, or **Business Settings →
  Accounts → WhatsApp Accounts**. Goes in Odoo as **WhatsApp Business
  Account ID (WABA ID)**.
- **Business ID**: your Business Portfolio's numeric ID, under **Business
  Settings → Business Info**. Goes in Odoo as **Meta Business ID**.

### A6. Generate a permanent Access Token (System User)
The token you get directly from the App Dashboard's "Generate access
token" button is **temporary — expires in ~24 hours** and is only meant
for quick testing. For Odoo (and any production use) you need a
**permanent token via a System User**:

1. **Business Settings → Users → System Users**.
2. Click **Add**, name it (e.g. "Odoo WhatsApp Integration"), set the role
   to **Admin**, click **Create System User**.
3. On that System User's row, click **Assign Assets → Apps**, select the
   Meta App from A2, enable **Full control**, click **Assign**.
4. Still on the System User, click **Generate Token**. Select the app,
   set an expiration (choose **Never** for production), and check these
   permissions:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
5. Click **Generate Token**. **Meta shows the token exactly once** — copy
   it immediately into a password manager before closing the dialog.
6. This is what goes in Odoo's **Access Token** field. It does not expire
   on its own; only manual revocation or removing the System User's asset
   access invalidates it.

### A7. App Secret (for webhook signature verification)
1. **App Dashboard → App Settings → Basic**.
2. Click **Show** next to **App Secret** (may require re-entering your
   Meta password).
3. This goes in Odoo's **App Secret** field. It's what the module's
   webhook controller uses to verify the `X-Hub-Signature-256` header Meta
   sends on every webhook POST — without it configured, the controller
   accepts unsigned webhooks (documented as a setup gap in the controller
   itself, not a silent security hole you'd hit by surprise).

### A8. Webhook — pick a Verify Token, then register it with Meta
1. Pick any random secret string yourself, e.g. generate one with
   `openssl rand -hex 24`. This is **not** issued by Meta — you invent it
   and put the same value in both places.
2. Put it in Odoo's **Webhook Verify Token** field (you can do this now or
   after the integration record is saved — either order works since Meta
   only checks it at the moment you click Meta's own "Verify and Save").
3. In the App Dashboard, go to **WhatsApp → Configuration → Webhook**.
4. Set:
   - **Callback URL**: `https://<your-odoo-domain>/webhook/whatsapp`
   - **Verify Token**: the same string from step 1
5. Click **Verify and Save**. Meta immediately sends a `GET` request to
   your callback URL with `hub.mode=subscribe`, `hub.verify_token=<your
   token>`, and `hub.challenge=<random string>` — the module's webhook
   controller checks the token against every `otm.whatsapp.integration`
   record and echoes the challenge back if it matches. If this fails,
   double-check the Odoo integration record was saved with the matching
   token **before** you click Verify and Save (Meta calls your live URL
   immediately, not a draft).
6. **Subscribe to webhook fields** — at minimum check:
   - `messages` (inbound messages — required)
   - `message_template_status_update` (template approval/rejection)
   You can add others (`account_alerts`, `phone_number_quality_update`,
   etc.) later; the module currently only processes `messages` and message
   `statuses` (sent/delivered/read/failed), which arrive automatically as
   part of the `messages` field subscription.

---

## Part B — Odoo-side setup (using this module)

### B1. Create the Integration record
**WhatsApp → Configuration → WhatsApp Integration → New**, fill in:

| Odoo field | Value from |
|---|---|
| Name | anything memorable, e.g. "Otomater Main WABA" |
| Business Account ID (WABA ID) | A5 |
| Business ID | A5 |
| Meta App ID | A2 |
| Access Token | A6 |
| Webhook Verify Token | A8 step 1 (your own invented string) |
| App Secret | A7 |
| Graph API Version | leave the default unless Meta has deprecated it — check `developers.facebook.com/docs/graph-api/changelog` if unsure |

Save the record.

### B2. Check Connection
Click **Check Connection** in the form header. This calls
`GET /<WABA_ID>` with your token — a green "Connected" status confirms the
token and WABA ID are both valid. If it errors, the message on the record
(`last_error`) is Meta's own error text, which is usually specific enough
to point at the exact wrong field (bad token vs. wrong WABA ID vs.
insufficient permissions).

### B3. Sync WhatsApp Numbers
Click **Sync WhatsApp Numbers**. This pulls every phone number registered
under the WABA (everything you set up in A3/A4) and creates one
`otm.whatsapp.phone` record per number, matched on Meta's `phone_number_id`
so re-running it never duplicates. Each new record shows:
- Display phone number, verified business name, quality rating
- `coexistence_status`, reflecting whatever Meta itself reports for that
  number (never assumed — see the module README's "What Is Actually
  Possible" section)

### B4. Assign numbers to teams/users
**WhatsApp → Configuration → WhatsApp Numbers**, open each number, set
**Assigned Team** / **Assigned Users**. Record rules restrict a plain
"WhatsApp / User" to only the numbers they're assigned to (directly, not
yet via team membership — see the module README's open items on
`lead.team`).

### B5. Sync Templates
**WhatsApp → Configuration → Templates → Sync Templates** (or the button on
the Integration form). Pulls every template already submitted/approved in
**WhatsApp Manager → Message Templates** on Meta's side — this module
doesn't submit new templates to Meta for approval, only reads existing
ones. Submit/approve templates directly in Meta's WhatsApp Manager first.

### B6. End-to-end test
1. From a personal phone, message the connected number.
2. Confirm it appears in **WhatsApp → Inbox** in Odoo within a few seconds
   — this proves the webhook round-trip (A8) is actually wired correctly,
   not just theoretically configured.
3. Reply from the Odoo Inbox. Confirm it arrives on the phone, and that in
   a Coexistence setup it also shows up in the phone's WhatsApp Business
   app thread (proving the mirroring, not just one-directional API send).

---

## Common failure points (checked against real setup reports)

| Symptom | Likely cause |
|---|---|
| Webhook "Verify and Save" fails in Meta's dashboard | Verify Token mismatch, or the Odoo integration record wasn't saved before clicking Verify — Meta calls the live URL immediately |
| Messages send but nothing arrives from customers | `messages` field not subscribed in A8 step 6, or firewall/reverse-proxy blocking Meta's inbound POSTs to `/webhook/whatsapp` |
| "Check Connection" fails with a permissions error | System User token missing `whatsapp_business_management`, or the System User's asset assignment (A6 step 3) doesn't include this specific App |
| Token stopped working after ~24 hours | You used the App Dashboard's quick "Generate access token" (temporary) instead of the System User permanent token (A6) |
| Coexistence number stopped receiving on the API side | WhatsApp Business app hasn't been opened on the phone in 14+ days (A4 step 6) |
| A newly connected number shows no history in Odoo | Expected — Meta only offers to sync recent 1:1 history (~6 months) at the moment of Coexistence connection, not retroactively later; older/already-missed history is not recoverable via API |

---

## Sources
Verified against Meta's own Cloud API "Get Started" documentation and
current (2026) third-party setup walkthroughs for the exact click-paths,
since Meta's dashboard wording shifts between releases:
- developers.facebook.com/documentation/business-messaging/whatsapp/get-started
- developers.facebook.com/documentation/business-messaging/whatsapp/whatsapp-business-accounts
- developers.facebook.com/blog/post/2022/12/05/auth-tokens (System User token flow)
- Multiple 2026 third-party Coexistence walkthroughs (Chakra, YCloud,
  Whautomate, Invent) cross-checked for the QR-scan/history-sync steps,
  since Meta doesn't publish a single canonical page for this flow
