# Autonomous email outreach: explicit opt-in only

The agent does **not require per-message human approval**. It is deliberately **not** an automated unsolicited cold-email sender. There is no reliable way to infer consent or all applicable laws merely from a public YouTube channel or public email address. Sending is OFF by default; do not enable until the hackathon organiser has approved automated email as a channel and you have documented the specific permission. Sender/operator remains accountable for legal compliance; code cannot certify it.

## Permitted path

1. Discover public YouTube accounts using the official API. Do not auto-comment, bulk-DM, bypass business-email reveal controls, scrape contact details or treat a public address as consent.
2. Research via HelloMinds; recover completed JSON via persisted aliases; verify source excerpts against captured content. No assumption of buying intent.
3. Only qualify leads meeting the scoring threshold **and** source-backed content needs. Store a price-free AI-disclosed draft in `outreach_drafts`.
4. A prospect must **affirmatively opt in to email** through an independent opt-in form, double-opt-in or inbound request. Store proof as a restricted-access HTTPS reference, the exact UTC time and jurisdiction; do **not** register an address merely because it is publicly shown. The optional API contact route is a trusted authenticated intake; its operator-provided proof is **not automatically validated** by the software. You must independently ensure the evidence is legitimate and the privacy notice is adequate.
5. Confirm exclusion list of relatives, friends, hackathon participants, prior contacts, and customers. Block them using `/suppression` for their channel identity and email (`mailto:address@domain`). Set `known_contact=true` or `excluded=true` if applicable. These API flags rely on correct input: central suppression must be populated before enabling sending.
6. After documented organiser approval, channel permission, domain verification and a working opt-out mailbox, an enabled worker dispatches without human review of individual emails. The provider receives a single plain-text email; any provider reply is an **acceptance**, not delivery or a sale.
7. Record replies (interested, question, opt-out) via authenticated `/outreach/replies` with a private evidence URL; this endpoint **does not fetch mail automatically**. To automate reply processing, connect a verified inbound mailbox/webhook; monitor STOP replies promptly and invoke `/outreach/optout` before further sending.

## Relevant law and platform conditions

UK ICO: individual subscribers (including sole traders and many partnerships) generally require consent or applicable soft opt-in for unsolicited marketing; UK corporate B2B emails do not have the same PECR consent requirement, but UK GDPR may apply to personal data. This code uses the **stricter explicit-opt-in-only policy** across recipients to avoid guessing subscriber classification or jurisdiction. An email address publicly shown on a social channel is **not consent**. Emails disclose the sender, identify AI assistance, provide working reply-to/STOP instructions and omit pricing. A separate privacy policy, data retention, lawful basis documentation and foreign-jurisdiction review are operational prerequisites. YouTube anti-spam rules prohibit mass commercial promotional comments; no YouTube messaging endpoints are implemented. Hackathon rules requiring organiser permission take priority; no configuration flag can substitute for actual approval.

Official guidance:
- https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/
- https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-direct-marketing-using-electronic-mail/how-do-we-comply-with-the-pecr-electronic-mail-marketing-rules/
- https://support.google.com/youtube/answer/2801973
- https://resend.com/docs/dashboard/emails/idempotency-keys

## Setup

- Preserve `.env`. Configure `AGENT_API_KEY` with an unpredictable strong secret; set SurrealDB credentials via protected deployment secrets.
- Run `sql/outreach_tables.surql` in the actual namespace/database, including `integration_test` if running live tests. Keep the existing `prospects`, `research_briefs`, `outreach_drafts`, and `suppression` tables.
- Verify a sending domain in Resend, set SPF/DKIM/DMARC, use a working Reply-To mailbox, and comply with provider terms and sending limits.
- Configure `OUTREACH_FROM_EMAIL`, `OUTREACH_REPLY_TO`, `OUTREACH_SENDER_NAME`, `RESEND_API_KEY`.
- Keep `OUTREACH_AUTOSEND_ENABLED=false` until actual permission is documented. After organiser approval, set `HACKATHON_OUTREACH_PERMISSION_GRANTED=true`, record `HACKATHON_PERMISSION_REFERENCE=https://...` to secure private evidence and set `OUTREACH_EMAIL_CHANNEL_PERMITTED=true`. Then set `OUTREACH_AUTOSEND_ENABLED=true`.
- `GET /outreach/status` reports readiness without exposing credentials.

## API workflow

```sh
# Authentication on every non-health endpoint when AGENT_API_KEY is set.
curl -H "X-Agent-Key: $AGENT_API_KEY" http://127.0.0.1:8005/outreach/status
```

Register a prospect's **actual** opted-in address (example values are fictional). This can trigger automatic sending if the prospect has a final research report, supported need, qualifies and has an unsent draft:

```sh
curl -X POST 'http://127.0.0.1:8005/outreach/contacts' \
  -H "X-Agent-Key: $AGENT_API_KEY" -H 'Content-Type: application/json' \
  -d '{
    "identity":"https://youtube.com/channel/UCexample",
    "email":"consenting-business@example.org",
    "source_url":"https://example.org/contact",
    "consent_reference":"https://private.example.org/opt-ins/evidence-123",
    "consent_at":"2026-11-11T08:00:00+00:00",
    "consent_method":"double_opt_in",
    "jurisdiction":"UK",
    "known_contact":false,
    "excluded":false
  }'
```

- `POST /outreach/dispatch?limit=2`: send ready, opted-in drafts without per-message review.
- `python -m scripts.dispatch_outreach --limit 2`: one-shot reconcile completed Minds tasks, then send eligible emails; suitable for an **externally configured** recurring Daytona scheduler. This project does **not** deploy a recurring scheduler.
- `GET /outreach/attempts`: accepted, unknown or failed delivery attempts. `unknown` requires investigation in Resend, **not** another automatic send.
- `POST /outreach/optout` `{"email":"..."}`: persist opt-out globally; also suppress matching profile identities.
- `POST /outreach/replies` `{"email":"...","type":"opt_out","evidence_reference":"https://private.example.org/..."}`: record an authenticated, externally verified inbound reply.

## Safety engineering and limitations

- **Fail closed** if authentication, SurrealDB, organiser permission, approved channel, sender credentials, target score, verified research evidence, opt-in, suppression checks or pricing-free message checks fail.
- **Global first-contact dedup**: `outreach_send_claims` keyed by recipient email, retained indefinitely while you operate. **UTC daily slots**: `outreach_daily_slots` uses atomic CREATE to cap contacts across Daytona sandboxes. A race or failure can consume a slot without sending; this is intentional.
- **No ambiguous retries**: provider failures are stored `unknown` and never resent automatically. Resend idempotency key provides an additional 24-hour duplicate protection window.
- Opt-out automation is **not complete** until a verified inbound mailbox/webhook feeds the supplied opt-out API. Someone must monitor the reply mailbox. Do not enable unattended live outreach without this.
- `OUTREACH_MAX_PER_DAY` is a contact safety cap, not a legal threshold or provider quota. No bulk recipient sending, follow-up chains, tracking pixels, scraping or social DMs.
- The software does not verify organiser correspondence, a claimed consent URL, sender account ownership, recipient country, lawful basis, actual email delivery, or paid subscriptions. Do not claim it guarantees legal compliance or hackathon eligibility.
- A consent record is not a lead qualification, and a completed research report is not recipient consent.
